"""Regression tests for the meaningful correctness risks in the GTFS compiler."""

import importlib.util
import io
from pathlib import Path
import unittest
import zipfile


SPEC = importlib.util.spec_from_file_location(
    "build_trains", Path(__file__).resolve().parents[1] / "scripts" / "build_trains.py"
)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class CompilerTests(unittest.TestCase):
    def test_polyline_uses_latitude_first_google_reference(self):
        points = [(-120.2, 38.5), (-120.95, 40.7), (-126.453, 43.252)]
        self.assertEqual(builder.encode_polyline(points), "_p~iF~ps|U_ulLnnqC_mqNvxq`@")

    def test_overnight_hours_are_not_wrapped(self):
        self.assertEqual(builder.parse_time("49:12:30"), 177150)
        self.assertIsNone(builder.parse_time("12:60:00"))

    def test_endpoint_placeholders_use_real_departure_and_arrival(self):
        times, error, corrections = builder.normalize_times([
            {"arrival_time": "00:00:00", "departure_time": "23:15:00"},
            {"arrival_time": "24:05:00", "departure_time": "24:10:00"},
            {"arrival_time": "26:00:00", "departure_time": "00:00:00"},
        ])
        self.assertIsNone(error)
        self.assertEqual(times, [(83700, 83700), (86700, 87000), (93600, 93600)])
        self.assertEqual(corrections, 2)

    def test_midnight_source_bug_is_rejected_not_inferred(self):
        times, error, _ = builder.normalize_times([
            {"arrival_time": "23:00:00", "departure_time": "23:00:00"},
            {"arrival_time": "47:53:00", "departure_time": "24:15:00"},
            {"arrival_time": "26:00:00", "departure_time": "26:00:00"},
        ])
        self.assertIsNone(times)
        self.assertEqual(error, "departure_before_arrival")

    def test_loop_station_visit_is_projected_to_later_position(self):
        points = [(116, 39), (116.02, 39), (116.02, 39.02), (116, 39.02), (116, 39), (115.98, 39)]
        # Revisiting the origin must advance along the loop, not snap back.
        distances, offset, error = builder.project_stations(
            [points[0], points[2], points[4], points[5]], points, 100
        )
        self.assertIsNone(error)
        self.assertLess(offset, 1)
        self.assertTrue(all(b > a for a, b in zip(distances, distances[1:])))
        self.assertGreater(distances[2], 7500)

    def test_off_route_station_rejected(self):
        result = builder.project_stations(
            [(116, 39), (117, 39)], [(116, 39), (116.1, 39)], 1500
        )
        self.assertEqual(result[2], "station_too_far_from_route")

    def test_calendar_is_bounded_and_exception_removes_service(self):
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            archive.writestr(
                "calendar.txt",
                "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                "S1,1,1,1,1,1,1,1,20261001,20261101\n",
            )
            archive.writestr(
                "calendar_dates.txt", "service_id,date,exception_type\n"
                "S1,20261013,2\nS2,20261014,1\nS2,20270101,1\n",
            )
        memory.seek(0)
        with zipfile.ZipFile(memory) as archive:
            services = builder.load_services(archive, "20261012", "20261014")
        self.assertEqual(services, {"S1": ["20261012", "20261014"], "S2": ["20261014"]})


if __name__ == "__main__":
    unittest.main()
