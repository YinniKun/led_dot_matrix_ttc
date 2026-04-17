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
        self.alerts_url = "https://bustime.ttc.ca/gtfsrt/alerts"
        
        # Matrix Hardware Configuration
        options = RGBMatrixOptions()
        options.rows = 32
        options.cols = 64
        options.chain_length = 1
        options.parallel = 1
        options.hardware_mapping = 'adafruit'
        options.drop_privileges = False       
        options.disable_hardware_pulsing = True  # Add this line
        options.gpio_slowdown = 4                # Increase this from 2 to 4 
        options.panel_type = "fm6126a"                # Slows the Pi 4 down so the matrix can read the data            

        self.matrix = RGBMatrix(options=options)
        self.canvas = self.matrix.CreateFrameCanvas()
        
        # Typography (CRITICAL: Using a smaller font to fit 4 lines)
        self.font = graphics.Font()
        # Ensure this points to your rpi-rgb-led-matrix fonts folder
        self.font.LoadFont("/home/ric/rpi-rgb-led-matrix/fonts/5x8.bdf") 
        
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
        self.subway_status = {'1': '', '2': '', '4': '', '5': ''}
        
        self.last_fetch_time = 0
        self.fetch_interval = 30 # Fetch new data every 30s

    def fetch_train_times(self, stop_id):
        """Pulls the live countdowns from the hidden API."""
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            response = requests.get(f"{self.ntas_base_url}{stop_id}", headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            if data and len(data) > 0:
                time_str = data[0].get("nextTrains", "")
                if time_str:
                    # Convert "0, 2, 3" into a list of integers [0, 2, 3]
                    return [int(x.strip()) for x in time_str.split(',')]
            return []
        except:
            return []

    def fetch_alerts(self):
        """Pulls GTFS-RT alerts and maps them to ! (delay) or x (no service)"""
        # Default all lines to running normally (represented by a dash)
        status = {'1': '-', '2': '-', '4': '-', '5': '-'}
        try:
            response = requests.get(self.alerts_url, timeout=5)
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)
            
            for entity in feed.entity:
                if entity.HasField('alert'):
                    for informed in entity.alert.informed_entity:
                        route = informed.route_id
                        # If the alert is for a subway line
                        if route in status:
                            # Check GTFS Effect Code (5 = NO_SERVICE, 3 = SIGNIFICANT_DELAYS)
                            if entity.alert.effect == 5:
                                status[route] = 'x'
                            else:
                                status[route] = '!'
            return status
        except Exception as e:
            print(f"Alerts Error: {e}")
            return status

    def update_data(self):
        """Updates all data streams."""
        self.east_times = self.fetch_train_times(self.east_stop)
        self.west_times = self.fetch_train_times(self.west_stop)
        self.subway_status = self.fetch_alerts()

    def format_time_string(self, times):
        if not times:
            return "No Data"
        return ", ".join([str(t) for t in times]) + "m"

    def run(self):
        print("Starting 4-Line Matrix. Press CTRL+C to stop.")
        
        try:
            while True:
                current_time = time.time()
                
                # Fetch new data asynchronously
                if current_time - self.last_fetch_time > self.fetch_interval:
                    self.update_data()
                    self.last_fetch_time = current_time

                self.canvas.Clear()
                
                # --- THE FLASHING LOGIC ---
                # This mathematically evaluates to True or False every 0.5 seconds
                flash_on = int(current_time * 2) % 2 == 0
                
                # --- LINE 1: Eastbound (Kennedy) ---
                east_str = self.format_time_string(self.east_times)
                # Check if the closest train is under the flash timeold and if the flash is currently on. If so, we set the color to black to create a flashing effect.
                if self.east_times and self.east_times[0] < self.flash_time and not flash_on:
                    east_color = self.black # Flash by turning the text black
                else:
                    east_color = self.green
                    
                graphics.DrawText(self.canvas, self.font, 1, 8, east_color, f"E: {east_str}")
                
                # --- LINE 2: Westbound (Kipling) ---
                west_str = self.format_time_string(self.west_times)
                if self.west_times and self.west_times[0] < self.flash_time and not flash_on:
                    west_color = self.black
                else:
                    west_color = self.green
                    
                graphics.DrawText(self.canvas, self.font, 1, 16, west_color, f"W: {west_str}")
                
                # --- LINE 3 & 4: System Alerts ---
                # Format: "L1: !   L2: -"
                s = self.subway_status
                
                # Line 3 (Displaying Lines 1 & 2 status)
                l1_color = self.red if s['1'] in ['x', '!'] else self.yellow
                l2_color = self.red if s['2'] in ['x', '!'] else self.green
                graphics.DrawText(self.canvas, self.font, 1, 24, l1_color, f"L1: {s['1']}")
                graphics.DrawText(self.canvas, self.font, 32, 24, l2_color, f"L2: {s['2']}")
                
                # Line 4 (Displaying Lines 3 & 4 status)
                l4_color = self.red if s['4'] in ['x', '!'] else self.purple
                graphics.DrawText(self.canvas, self.font, 1, 32, self.white, f"L4: {s['4']}")
                graphics.DrawText(self.canvas, self.font, 32, 32, l4_color, f"L5: {s['5']}")

                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                
                # Fast loop to maintain the 0.5s flashing animation precision
                time.sleep(0.05)
                
        except KeyboardInterrupt:
            print("\nExiting.")
            self.matrix.Clear()

if __name__ == "__main__":
    # 13757 = Bay Eastbound
    # 13758 = Bay Westbound
    display = TTCCommandCenter(east_stop='13757', west_stop='13758', flash_time=3)
    display.run()