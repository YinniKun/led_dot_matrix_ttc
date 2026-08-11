import time
import requests
import datetime
import re
from google.transit import gtfs_realtime_pb2

# Try importing hardware rgbmatrix; fallback to mock classes if on non-Pi hardware (for testing/dev)
try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics
    HAS_HARDWARE_MATRIX = True
except ImportError:
    HAS_HARDWARE_MATRIX = False

    class RGBMatrixOptions:
        def __init__(self):
            self.rows = 32
            self.cols = 64
            self.chain_length = 1
            self.parallel = 1
            self.hardware_mapping = 'adafruit-hat'
            self.drop_privileges = False
            self.disable_hardware_pulsing = True
            self.gpio_slowdown = 4
            self.panel_type = "fm6126a"

    class CanvasMock:
        def __init__(self, width=64, height=32):
            self.width = width
            self.height = height
            self.buffer = [[(0, 0, 0) for _ in range(width)] for _ in range(height)]
        
        def Clear(self):
            self.buffer = [[(0, 0, 0) for _ in range(self.width)] for _ in range(self.height)]
            
        def SetPixel(self, x, y, r, g, b):
            if 0 <= x < self.width and 0 <= y < self.height:
                self.buffer[int(y)][int(x)] = (r, g, b)

    class RGBMatrix:
        def __init__(self, options=None):
            self.options = options or RGBMatrixOptions()
            self.width = self.options.cols
            self.height = self.options.rows
            
        def CreateFrameCanvas(self):
            return CanvasMock(self.width, self.height)
            
        def SwapOnVSync(self, canvas):
            return CanvasMock(self.width, self.height)
            
        def Clear(self):
            pass

    class GraphicsMock:
        class Color:
            def __init__(self, r, g, b):
                self.red = r
                self.green = g
                self.blue = b
                
        class Font:
            def LoadFont(self, path):
                pass

        @staticmethod
        def DrawText(canvas, font, x, y, color, text):
            return len(text) * 4
            
        @staticmethod
        def DrawCircle(canvas, x, y, r, color):
            pass

        @staticmethod
        def DrawLine(canvas, x1, y1, x2, y2, color):
            pass

    graphics = GraphicsMock()

class TTCCommandCenter:
    def __init__(self, east_stop, west_stop, flash_time=3, go_api_key=None, rotate_interval=5.0):
        # Stop IDs & Config
        self.east_stop = str(east_stop)
        self.west_stop = str(west_stop)
        self.flash_time = flash_time
        self.go_api_key = go_api_key
        self.rotate_interval = rotate_interval
        
        # API Endpoints
        self.ntas_base_url = "https://ntas.ttc.ca/api/ntas/get-next-train-time/"
        self.alerts_url = "https://gtfsrt.ttc.ca/alerts/subway?format=text"
        self.weather_url = "https://api.open-meteo.com/v1/forecast?latitude=43.6532&longitude=-79.3832&current_weather=true&timezone=America%2FToronto"
        self.go_updates_url = "https://www.gotransit.com/en/service-updates"
        
        # Matrix Hardware Configuration
        options = RGBMatrixOptions()
        options.rows = 32
        options.cols = 64
        options.chain_length = 1
        options.parallel = 1
        options.hardware_mapping = 'adafruit-hat'
        options.drop_privileges = False       
        options.disable_hardware_pulsing = True  
        options.gpio_slowdown = 4                
        options.panel_type = "fm6126a"                

        self.matrix = RGBMatrix(options=options)
        self.canvas = self.matrix.CreateFrameCanvas()
        
        # Typography (4x6 BDF font)
        self.font = graphics.Font()
        if HAS_HARDWARE_MATRIX:
            self.font.LoadFont("/home/ric/rpi-rgb-led-matrix/fonts/4x6.bdf") 
        
        # Base Colours
        self.green = graphics.Color(22, 167, 83)   # Line 2
        self.yellow = graphics.Color(248, 195, 2)  # Line 1
        self.purple = graphics.Color(128, 0, 128)  # Line 4
        self.orange = graphics.Color(255, 153, 85)  # Line 5
        self.red = graphics.Color(220, 0, 0)       # Alerts / No Service
        self.white = graphics.Color(255, 255, 255)
        self.black = graphics.Color(0, 0, 0)
        
        # GO Transit Line Colours
        self.go_green = graphics.Color(0, 133, 66)   # GO Transit Green
        self.go_brown = graphics.Color(121, 69, 0)   # Stouffville Line Color
        
        # Weather Colours (reflecting the weather condition)
        self.sunny_color = graphics.Color(255, 215, 0)   # Bright Yellow / Gold for Sun
        self.cloudy_color = graphics.Color(170, 200, 230) # Light Cyan-Gray for Cloud
        self.rain_color = graphics.Color(0, 190, 255)    # Electric Blue for Rain
        self.snow_color = graphics.Color(240, 250, 255)  # Ice White for Snow
        
        # State Variables
        self.east_times = []
        self.west_times = []
        self.subway_status = {'1': 'OK', '2': 'OK', '4': 'OK', '5': 'OK'}
        self.weather_temp = 20
        self.weather_condition = 'SUNNY' # SUNNY, CLOUDY, RAIN, SNOW
        self.go_status = {'LW': 'OK', 'ST': 'OK'} # Lake Shore West and Stouffville Line only
        
        self.last_fetch_time = 0
        self.fetch_interval = 30 

    def fetch_train_times(self, stop_id):
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            response = requests.get(f"{self.ntas_base_url}{stop_id}", headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            if data and len(data) > 0:
                time_str = data[0].get("nextTrains", "")
                if time_str:
                    return [int(x.strip()) for x in time_str.split(',')]
            return []
        except:
            return []

    def fetch_alerts(self):
        """Pulls subway alerts from the TTC's plain-text GTFS-RT feed."""
        status = {'1': 'OK', '2': 'OK', '4': 'OK', '5': 'OK'}
        
        try:
            headers = {'User-Agent': 'RaspberryPi-Matrix-Display/1.0'}
            response = requests.get(self.alerts_url, headers=headers, timeout=5)
            
            if response.status_code != 200:
                return status
                
            text_data = response.text
            current_time = int(time.time())
            
            # Split the giant text blob into individual alert blocks
            alert_blocks = text_data.split('\nentity {')
            
            for block in alert_blocks:
                # Time window checker
                if "active_period" in block:
                    is_active = False
                    periods = re.findall(r'active_period\s*\{([^\}]+)\}', block)
                    
                    for p in periods:
                        start_match = re.search(r'start:\s*(\d+)', p)
                        end_match = re.search(r'end:\s*(\d+)', p)
                        
                        start_time = int(start_match.group(1)) if start_match else 0
                        end_time = int(end_match.group(1)) if end_match else 2147483647 
                        
                        if start_time <= current_time <= end_time:
                            is_active = True
                            break
                    
                    if not is_active:
                        continue

                # Skip future maintenance banners
                if 'cause: MAINTENANCE' in block and 'effect: REDUCED_SERVICE' in block:
                    continue        
                
                # Subway line checker
                for line in status.keys():
                    if f'route_id: "{line}"' in block or f'route_id: "Line {line}"' in block:
                        if 'effect: NO_SERVICE' in block:
                            status[line] = 'x'
                        else:
                            if status[line] != 'x':
                                status[line] = '!'
                                
            return status
            
        except Exception as e:
            print(f"Plain-Text Alerts Error: {e}")
            return status

    def fetch_weather(self):
        """Fetches current temperature and weather condition (SUNNY, CLOUDY, RAIN, SNOW)."""
        try:
            r = requests.get(self.weather_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            if r.status_code == 200:
                data = r.json().get('current_weather', {})
                temp = round(data.get('temperature', 20))
                code = data.get('weathercode', 0)
                
                # WMO weather code mapping
                if code == 0:
                    condition = 'SUNNY'
                elif code in [1, 2, 3, 45, 48]:
                    condition = 'CLOUDY'
                elif code in [71, 73, 75, 77, 85, 86]:
                    condition = 'SNOW'
                else:
                    condition = 'RAIN'
                    
                return temp, condition
        except Exception as e:
            print(f"Weather Fetch Error: {e}")
            
        return self.weather_temp, self.weather_condition

    def fetch_go_status(self):
        """Fetches status for Lake Shore West (LW) and Stouffville (ST) lines only."""
        status = {'LW': 'OK', 'ST': 'OK'}
        
        # 1. Official OpenMetrolinx API if key provided
        if self.go_api_key:
            try:
                url = f"https://api.openmetrolinx.com/OpenDataAPI/api/v1/ServiceUpdate/ServiceAlert/All?key={self.go_api_key}"
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    if data.get('Metadata', {}).get('ErrorCode') == '200':
                        messages = data.get('Messages', [])
                        for msg in messages:
                            lines = [str(l).lower() for l in msg.get('Lines', [])]
                            text = (str(msg.get('Subject', '')) + ' ' + str(msg.get('Body', ''))).lower()
                            
                            is_lw = any('lw' in l or 'lakeshore west' in l for l in lines) or 'lakeshore west' in text or 'lake shore west' in text
                            is_st = any('st' in l or 'stouffville' in l for l in lines) or 'stouffville' in text
                            
                            stat_code = 'x' if ('cancel' in text or 'no service' in text or 'suspend' in text) else '!'
                            if is_lw:
                                status['LW'] = stat_code
                            if is_st:
                                status['ST'] = stat_code
                        return status
            except Exception as e:
                print(f"GO API Fetch Error: {e}")

        # 2. Web fallback parsing from gotransit.com __NEXT_DATA__
        try:
            r = requests.get(self.go_updates_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            if r.status_code == 200:
                match = re.search(r'<script id=\"__NEXT_DATA__\" type=\"application/json\">(.*?)</script>', r.text, re.DOTALL)
                if match:
                    blob = match.group(1).lower()
                    
                    # Check Lake Shore West line
                    if 'lakeshore west' in blob or 'lake shore west' in blob:
                        if 'lakeshore west delay' in blob or 'lakeshore west cancellation' in blob or 'lakeshore west disruption' in blob:
                            status['LW'] = '!'
                        elif 'lakeshore west no service' in blob or 'lakeshore west suspended' in blob:
                            status['LW'] = 'x'
                            
                    # Check Stouffville line
                    if 'stouffville' in blob:
                        if 'stouffville delay' in blob or 'stouffville cancellation' in blob or 'stouffville disruption' in blob:
                            status['ST'] = '!'
                        elif 'stouffville no service' in blob or 'stouffville suspended' in blob:
                            status['ST'] = 'x'
        except Exception as e:
            print(f"GO Web Fetch Error: {e}")
            
        return status

    def update_data(self):
        self.east_times = self.fetch_train_times(self.east_stop)
        self.west_times = self.fetch_train_times(self.west_stop)
        self.subway_status = self.fetch_alerts()
        self.weather_temp, self.weather_condition = self.fetch_weather()
        self.go_status = self.fetch_go_status()

    # --- DRAWING HELPERS ---
    def draw_line_badge(self, x, y, line_num, circle_color, text_color):
        """Draws the filled TTC circle with the number inside."""
        for r in range(4):
            graphics.DrawCircle(self.canvas, x + 4, y - 2, r, circle_color)
        graphics.DrawText(self.canvas, self.font, x + 3, y + 1, text_color, str(line_num))

    def draw_arrival_times(self, x, y, times, color_normal, color_flash, flash_on):
        """Draws arrival countdown times."""
        if not times:
            graphics.DrawText(self.canvas, self.font, x, y, self.white, "No Data")
            return

        current_x = x
        for i, t in enumerate(times):
            is_arriving = (t <= self.flash_time)
            
            if is_arriving and not flash_on:
                draw_color = self.black
            elif is_arriving:
                draw_color = color_flash
            else:
                draw_color = color_normal
                
            time_str = str(t) + ("," if i < len(times)-1 else "m")
            width = graphics.DrawText(self.canvas, self.font, current_x, y, draw_color, time_str)
            current_x += width + 1

    def draw_weather_symbol(self, x, y, condition, color):
        """Draws a 5x5 custom pixel symbol for SUNNY, CLOUDY, RAIN, or SNOW."""
        r, g, b = color.red, color.green, color.blue
        
        if condition == 'SUNNY':
            # 5x5 Sun symbol with radiant rays
            pixels = [
                (2, 0),
                (1, 1), (2, 1), (3, 1),
                (0, 2), (1, 2), (2, 2), (3, 2), (4, 2),
                (1, 3), (2, 3), (3, 3),
                (2, 4)
            ]
            for px, py in pixels:
                self.canvas.SetPixel(x + px, y + py, r, g, b)
                
        elif condition == 'CLOUDY':
            # 6x4 Cloud shape
            pixels = [
                (1, 0), (2, 0), (3, 0),
                (0, 1), (1, 1), (2, 1), (3, 1), (4, 1),
                (0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (5, 2),
                (1, 3), (2, 3), (3, 3), (4, 3)
            ]
            for px, py in pixels:
                self.canvas.SetPixel(x + px, y + py, r, g, b)
                
        elif condition == 'RAIN':
            # Cloud top + rain drops below
            cloud_px = [(1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (3, 1), (4, 1)]
            rain_px = [(1, 3), (3, 3), (0, 4), (2, 4)]
            for px, py in cloud_px:
                self.canvas.SetPixel(x + px, y + py, r, g, b)
            # Blue rain drops
            for px, py in rain_px:
                self.canvas.SetPixel(x + px, y + py, 0, 190, 255)
                
        elif condition == 'SNOW':
            # 5x5 Snowflake asterisk
            pixels = [
                (0, 0), (2, 0), (4, 0),
                (1, 1), (2, 1), (3, 1),
                (0, 2), (1, 2), (2, 2), (3, 2), (4, 2),
                (1, 3), (2, 3), (3, 3),
                (0, 4), (2, 4), (4, 4)
            ]
            for px, py in pixels:
                self.canvas.SetPixel(x + px, y + py, r, g, b)

    # --- ROTATING BOTTOM SCREEN DRAW ROUTINES ---
    def draw_screen_1(self, y=27):
        """Screen (1): TTC Subway Line status for lines 1, 2, 4, 5."""
        x_offset = 1
        for line, color in [('1', self.yellow), ('2', self.green), ('4', self.purple), ('5', self.orange)]:
            status = self.subway_status.get(line, 'OK')
            stat_color = self.red if status in ['x', '!'] else self.white
            
            w1 = graphics.DrawText(self.canvas, self.font, x_offset, y, color, line)
            w2 = graphics.DrawText(self.canvas, self.font, x_offset + w1, y, stat_color, status)
            x_offset += w1 + w2 + 5

    def draw_screen_2(self, y=27):
        """Screen (2): Current Weather (Left: temp, Middle: time HH:MM, Right: weather symbol & color)."""
        # Left: Current temperature
        temp_str = f"{self.weather_temp}°C"
        graphics.DrawText(self.canvas, self.font, 1, y, self.white, temp_str)
        
        # Middle: Current time (Hour and minute)
        time_str = datetime.datetime.now().strftime('%H:%M')
        graphics.DrawText(self.canvas, self.font, 22, y, self.white, time_str)
        
        # Right: Current weather symbol & condition color
        weather_colors = {
            'SUNNY': self.sunny_color,
            'CLOUDY': self.cloudy_color,
            'RAIN': self.rain_color,
            'SNOW': self.snow_color
        }
        color = weather_colors.get(self.weather_condition, self.sunny_color)
        
        # Draw weather condition pixel icon at right edge (X=54)
        self.draw_weather_symbol(54, y - 5, self.weather_condition, color)

    def draw_screen_3(self, y=27):
        """Screen (3): GO Transit line status for Lake Shore West and Stouffville Line ONLY."""
        # Left: Lake Shore West Line (LW)
        x_offset = 1
        w1 = graphics.DrawText(self.canvas, self.font, x_offset, y, self.go_green, "LW:")
        lw_stat = self.go_status.get('LW', 'OK')
        lw_color = self.red if lw_stat in ['x', '!'] else self.white
        w2 = graphics.DrawText(self.canvas, self.font, x_offset + w1, y, lw_color, lw_stat)
        
        # Right: Stouffville Line (ST)
        x_offset = 33
        w3 = graphics.DrawText(self.canvas, self.font, x_offset, y, self.go_green, "ST:")
        st_stat = self.go_status.get('ST', 'OK')
        st_color = self.red if st_stat in ['x', '!'] else self.white
        w4 = graphics.DrawText(self.canvas, self.font, x_offset + w3, y, st_color, st_stat)

    def run(self):
        print("Starting 3-Line Matrix with Rotating Bottom Screen. Press CTRL+C to stop.")
        
        try:
            while True:
                current_time = time.time()
                
                if current_time - self.last_fetch_time > self.fetch_interval:
                    self.update_data()
                    self.last_fetch_time = current_time

                self.canvas.Clear()
                flash_on = int(current_time * 2) % 2 == 0
                
                # --- LINE 1: Eastbound (Row 8) ---
                self.draw_line_badge(0, 8, 2, self.green, self.white)
                text_width = graphics.DrawText(self.canvas, self.font, 11, 8, self.white, "E:Ken")
                self.draw_arrival_times(11 + text_width + 2, 8, self.east_times, self.orange, self.red, flash_on)
                
                # --- LINE 2: Westbound (Row 17) ---
                self.draw_line_badge(0, 17, 2, self.green, self.white)
                text_width = graphics.DrawText(self.canvas, self.font, 11, 17, self.white, "W:Kip")
                self.draw_arrival_times(11 + text_width + 2, 17, self.west_times, self.orange, self.red, flash_on)
                
                # --- LINE 3: ROTATING BOTTOM SCREEN (Row 27) ---
                # Screen 0: TTC Subway Status (1, 2, 4, 5)
                # Screen 1: Weather & Time (Temp, HH:MM, Weather Symbol)
                # Screen 2: GO Transit Status (Lake Shore West & Stouffville Line)
                screen_index = int(current_time / self.rotate_interval) % 3
                
                if screen_index == 0:
                    self.draw_screen_1(27)
                elif screen_index == 1:
                    self.draw_screen_2(27)
                elif screen_index == 2:
                    self.draw_screen_3(27)

                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                time.sleep(0.05)
                
        except KeyboardInterrupt:
            print("\nExiting.")
            self.matrix.Clear()

if __name__ == "__main__":
    display = TTCCommandCenter(east_stop='13757', west_stop='13758', flash_time=3)
    display.run()