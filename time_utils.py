"""
Centralized game-time helpers.

Internal canonical representation:
- Day number is 1-based integer (Day 1, Day 2, ...)
- Time-of-day is minutes since midnight (0..1439)
- Absolute time is minutes since Day 1 12:00 AM:
    abs_minutes = (day-1)*1440 + minutes_since_midnight
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple
import logging

@dataclass(frozen=True)
class GameTime:
    day: int
    hour: int
    minute: int
    ampm: str

def advance_time(current_day: int, time_string: str, minutes_to_add: int) -> tuple[int, str]:
    """
    Advances the given time by a set number of minutes, returning the new day and formatted time string.
    
    Args:
        current_day (int): The starting day.
        time_string (str): The starting time in "HH:MM A.M." or "HH:MM P.M." format.
        minutes_to_add (int): The number of minutes to advance.
        
    Returns:
        tuple[int, str]: The new day and the new formatted time string.
    """
    try:
        # Split safely by spaces (e.g., "01:30 P.M." -> ["01:30", "P.M."])
        time_parts = time_string.strip().split()
        clock_part = time_parts[0]
        # Remove any dots to standardize checking "AM" vs "PM"
        am_pm_part = time_parts[1].upper().replace(".", "") if len(time_parts) > 1 else "AM"
        
        # Split the clock part by colon
        hour, minute = map(int, clock_part.split(":"))
        
        # Convert to 24-hour format temporarily so the math is super easy
        if am_pm_part == "PM" and hour != 12:
            hour += 12
        elif am_pm_part == "AM" and hour == 12:
            hour = 0
            
        # Add the new minutes
        total_minutes = minute + minutes_to_add
        
        # Calculate how many hours we just made, and what the leftover minutes are
        extra_hours = total_minutes // 60
        new_minute = total_minutes % 60
        
        total_hours = hour + extra_hours
        
        # Calculate how many days we rolled over
        days_passed = total_hours // 24
        new_hour_24 = total_hours % 24
        new_day = current_day + days_passed
        
        # Convert back to a 12-hour format string for display
        new_am_pm = "P.M." if new_hour_24 >= 12 else "A.M."
        new_hour_12 = new_hour_24 % 12
        if new_hour_12 == 0:
            new_hour_12 = 12
            
        # Format the output with :02d so single digit minutes get a leading zero (e.g., "05")
        new_time_string = f"{new_hour_12}:{new_minute:02d} {new_am_pm}"
        
        return new_day, new_time_string
        
    except Exception as error:
        logging.error(f"Error calculating time: {error}. Falling back to original time.")
        return current_day, time_string

def is_time_passed(current_day: int, current_time_string: str, target_day: int, target_time_string: str) -> bool:
    """
    Compares two string-based times to see if the current time has passed the target time.
    """
    if current_day > target_day:
        return True
    if current_day < target_day:
        return False
        
    # If it's the exact same day, convert both times to 24-hour minutes to easily compare them
    def _get_24h_minutes(time_str: str) -> int:
        try:
            parts = time_str.strip().split()
            h, m = map(int, parts[0].split(":"))
            am_pm = parts[1].upper().replace(".", "") if len(parts) > 1 else "AM"
            if am_pm == "PM" and h != 12: h += 12
            if am_pm == "AM" and h == 12: h = 0
            return (h * 60) + m
        except Exception:
            return 0
            
    return _get_24h_minutes(current_time_string) >= _get_24h_minutes(target_time_string)