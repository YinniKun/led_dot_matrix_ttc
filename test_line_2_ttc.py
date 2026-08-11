import unittest
import time
from line_2_ttc import TTCCommandCenter, HAS_HARDWARE_MATRIX

class TestTTCCommandCenter(unittest.TestCase):
    def setUp(self):
        self.display = TTCCommandCenter(east_stop='13757', west_stop='13758', flash_time=3, rotate_interval=5.0)

    def test_initialization(self):
        self.assertEqual(self.display.east_stop, '13757')
        self.assertEqual(self.display.west_stop, '13758')
        self.assertEqual(self.display.flash_time, 3)
        self.assertEqual(self.display.rotate_interval, 5.0)
        self.assertIn('1', self.display.subway_status)
        self.assertIn('LW', self.display.go_status)
        self.assertIn('ST', self.display.go_status)

    def test_fetch_weather(self):
        temp, condition = self.display.fetch_weather()
        self.assertIsInstance(temp, int)
        self.assertIn(condition, ['SUNNY', 'CLOUDY', 'RAIN', 'SNOW'])

    def test_fetch_go_status(self):
        status = self.display.fetch_go_status()
        self.assertIsInstance(status, dict)
        self.assertIn('LW', status)
        self.assertIn('ST', status)
        # Verify status is only for Lake Shore West and Stouffville Line
        self.assertEqual(set(status.keys()), {'LW', 'ST'})
        self.assertIn(status['LW'], ['OK', '!', 'x'])
        self.assertIn(status['ST'], ['OK', '!', 'x'])

    def test_fetch_alerts(self):
        alerts = self.display.fetch_alerts()
        self.assertIsInstance(alerts, dict)
        for line in ['1', '2', '4', '5']:
            self.assertIn(line, alerts)
            self.assertIn(alerts[line], ['OK', '!', 'x'])

    def test_draw_screens(self):
        # Update state data
        self.display.update_data()
        
        # Test Screen 1 (TTC subway status)
        self.display.canvas.Clear()
        self.display.draw_screen_1(27)
        
        # Test Screen 2 (Weather & Time)
        self.display.canvas.Clear()
        self.display.draw_screen_2(27)
        
        # Test Screen 3 (GO Transit status - LW & ST)
        self.display.canvas.Clear()
        self.display.draw_screen_3(27)

    def test_weather_symbols(self):
        for cond in ['SUNNY', 'CLOUDY', 'RAIN', 'SNOW']:
            self.display.canvas.Clear()
            color = getattr(self.display, f"{cond.lower()}_color", self.display.sunny_color)
            self.display.draw_weather_symbol(54, 22, cond, color)

    def test_rotating_screen_index(self):
        # Screen rotation logic: int(time / rotate_interval) % 3
        test_times = [
            (0.0, 0),  # Screen 1
            (2.5, 0),  # Screen 1
            (5.0, 1),  # Screen 2
            (7.5, 1),  # Screen 2
            (10.0, 2), # Screen 3
            (12.5, 2), # Screen 3
            (15.0, 0), # Screen 1 (cycle resets)
        ]
        for t, expected_screen in test_times:
            screen_index = int(t / self.display.rotate_interval) % 3
            self.assertEqual(screen_index, expected_screen, f"At t={t}, expected screen {expected_screen} but got {screen_index}")

if __name__ == '__main__':
    unittest.main()
