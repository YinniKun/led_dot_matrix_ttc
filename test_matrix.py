import time
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics

print("Initializing Matrix...")

options = RGBMatrixOptions()
options.rows = 32
options.cols = 64
options.chain_length = 1
options.parallel = 1
options.hardware_mapping = 'adafruit'
options.drop_privileges = False

# THE CRITICAL PI 4 FIXES
options.disable_hardware_pulsing = True  # Bypasses the audio timer conflict
options.gpio_slowdown = 5
options.panel_type = "fm6126a"                # Slows the Pi 4 down so the matrix can read the data

try:
    matrix = RGBMatrix(options=options)
    canvas = matrix.CreateFrameCanvas()

    # Draw a Red Border
    for x in range(0, matrix.width):
        canvas.SetPixel(x, 0, 255, 0, 0)
        canvas.SetPixel(x, matrix.height - 1, 255, 0, 0)
    for y in range(0, matrix.height):
        canvas.SetPixel(0, y, 255, 0, 0)
        canvas.SetPixel(matrix.width - 1, y, 255, 0, 0)

    # Load Font and Draw Green Text
    font = graphics.Font()
    # Update this path if your fonts folder is somewhere else
    font.LoadFont("/home/ric/rpi-rgb-led-matrix/fonts/7x13.bdf") 
    textColor = graphics.Color(0, 255, 0) 
    
    graphics.DrawText(canvas, font, 20, 20, textColor, "OK!")

    # Push to the LEDs
    canvas = matrix.SwapOnVSync(canvas)
    
    print("Matrix should be displaying a Red Border and Green 'OK!'. Holding for 20 seconds...")
    time.sleep(2000)

except Exception as e:
    print(f"Failed to run: {e}")

finally:
    matrix.Clear()
    print("Test complete. Matrix cleared.")