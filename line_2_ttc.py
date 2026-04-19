import time
import requests
from google.transit import gtfs_realtime_pb2
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics

class TTCCommandCenter:
    def __init__(self, east_stop, west_stop, flash_time=3):
        # Stop IDs
        self.east_stop = str(east_stop)
        self.west_stop = str(west_stop)
        self.flash_time = flash_time
        
        # API Endpoints
        self.ntas_base_url = "https://ntas.ttc.ca/api/ntas/get-next-train-time/"
        self.alerts_url = "https://gtfsrt.ttc.ca/alerts/subway?format=text"
        
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
        
        # Typography (CRITICAL: Changed to 4x6 to fit all the data)
        self.font = graphics.Font()
        self.font.LoadFont("/home/ric/rpi-rgb-led-matrix/fonts/4x6.bdf") 
        
        # Colours
        self.green = graphics.Color(22, 167, 83)  # Line 2
        self.yellow = graphics.Color(248, 195, 2) # Line 1
        self.purple = graphics.Color(128, 0, 128) # Line 4
        self.orange = graphics.Color(255, 153, 85)   # Line 5
        self.red = graphics.Color(220, 0, 0)      # Alerts / No Service
        self.white = graphics.Color(255, 255, 255)
        self.black = graphics.Color(0, 0, 0)
        
        # State Variables
        self.east_times = []
        self.west_times = []
        self.subway_status = {'1': '-', '2': '-', '4': '-', '5': '-'}
        
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
        status = {'1': '-', '2': '-', '4': '-', '5': '-'}
        
        try:
            # We use an honest, custom User-Agent. Firewalls are often more forgiving 
            # of custom script names on text endpoints than fake Chrome browsers.
            headers = {'User-Agent': 'RaspberryPi-Matrix-Display/1.0'}
            response = requests.get(self.alerts_url, headers=headers, timeout=5)
            
            if response.status_code != 200:
                return status
                
            text_data = response.text
            
            # Split the giant text blob into individual alert blocks
            alert_blocks = text_data.split('entity {')
            
            for block in alert_blocks:
                # Check each subway line
                for line in status.keys():
                    # The plain text feed formats it literally as: route_id: "1"
                    if f'route_id: "{line}"' in block or f'route_id: "Line {line}"' in block:
                        if 'effect: NO_SERVICE' in block:
                            status[line] = 'x' # Hard closure
                        else:
                            # If it's just a delay, only set it to '!' if it isn't already 'x'
                            if status[line] != 'x':
                                status[line] = '!'
                                
            return status
            
        except Exception as e:
            print(f"Plain-Text Alerts Error: {e}")
            return status

    def update_data(self):
        self.east_times = self.fetch_train_times(self.east_stop)
        self.west_times = self.fetch_train_times(self.west_stop)
        self.subway_status = self.fetch_alerts()

    # --- NEW DRAWING HELPERS ---
    def draw_line_badge(self, x, y, line_num, circle_color, text_color):
        """Draws the filled TTC circle with the number inside."""
        for r in range(4):
            graphics.DrawCircle(self.canvas, x + 4, y - 2, r, circle_color)
        graphics.DrawText(self.canvas, self.font, x + 3, y + 1, text_color, str(line_num))

    def draw_arrival_times(self, x, y, times, color_normal, color_flash, flash_on):
        """Draws times, flashing ONLY the specific trains under the threshold."""
        if not times:
            graphics.DrawText(self.canvas, self.font, x, y, self.white, "No Data")
            return

        current_x = x
        for i, t in enumerate(times):
            is_arriving = (t <= self.flash_time)
            
            # Flash logic: turn black if it's arriving AND flash is off
            if is_arriving and not flash_on:
                draw_color = self.black
            elif is_arriving:
                draw_color = color_flash
            else:
                draw_color = color_normal
                
            # Add a comma to all times except the last one, and an 'm' to the very last one
            time_str = str(t) + ("," if i < len(times)-1 else "m")
            
            width = graphics.DrawText(self.canvas, self.font, current_x, y, draw_color, time_str)
            current_x += width + 2 # Add a tiny 2px gap between numbers

    def run(self):
        print("Starting 3-Line Matrix. Press CTRL+C to stop.")
        
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
                
                # --- LINE 3: System Status (Row 27) ---
                # Formats all 4 lines tightly on one row like: "1- 2! 4x 5-"
                x_offset = 1
                for line, color in [('1', self.yellow), ('2', self.green), ('4', self.purple), ('5', self.orange)]:
                    status = self.subway_status.get(line, 'OK')
                    stat_color = self.red if status in ['x', '!'] else self.white
                    
                    # Draw Line # and Status Symbol right next to it
                    w1 = graphics.DrawText(self.canvas, self.font, x_offset, 27, color, line)
                    w2 = graphics.DrawText(self.canvas, self.font, x_offset + w1, 27, stat_color, status)
                    
                    x_offset += w1 + w2 + 5 # Add 5px spacing before the next subway line

                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                time.sleep(0.05)
                
        except KeyboardInterrupt:
            print("\nExiting.")
            self.matrix.Clear()

if __name__ == "__main__":
    display = TTCCommandCenter(east_stop='13757', west_stop='13758', flash_time=3)
    display.run()