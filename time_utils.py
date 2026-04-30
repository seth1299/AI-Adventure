"""
Centralized game-time helpers.

Internal canonical representation:
- Day number is 1-based integer (Day 1, Day 2, ...)
- Time-of-day is minutes since midnight (0..1439)
- Absolute time is minutes since Day 1 12:00 AM:
    abs_minutes = (day-1)*1440 + minutes_since_midnight
"""

from __future__ import annotations
import logging, random

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

def calculate_calendar_date(absolute_day: int, calendar_settings: dict) -> str:
    """
    Calculates the rich calendar date string (Weekday, Month, Day, Year, Season)
    based on an absolute day integer and custom calendar settings.
    
    Args:
        absolute_day (int): The total number of days that have passed since Day 1.
        calendar_settings (dict): The dictionary containing weekdays and month definitions.
        
    Returns:
        str: A formatted date string, or a fallback "Day X" if no calendar is set.
    """
    if not calendar_settings:
        logging.warning("NO CALENDAR SETTINGS PROVIDED.")
        return f"Day {absolute_day}"

    weekdays = calendar_settings.get("weekdays", [])
    months = calendar_settings.get("months", [])

    if not weekdays or not months:
        logging.warning("NO WEEKDAYS OR MONTHS IN CALENDAR.")
        return f"Day {absolute_day}"

    try:
        # 1. Weekday Calculation
        weekday_index = (absolute_day - 1) % len(weekdays)
        weekday_name = weekdays[weekday_index]

        # 2. Year and Month Calculation
        total_days_in_year = sum(max(1, month.get("days", 30)) for month in months)

        if total_days_in_year <= 0:
             logging.warning("NO TOTAL DAYS IN YEAR.")
             return f"Day {absolute_day}"

        # Calculate current year and the current day within that specific year
        year = ((absolute_day - 1) // total_days_in_year) + 1
        day_of_year = (absolute_day - 1) % total_days_in_year

        current_month = months[0]
        day_of_month = day_of_year + 1

        days_accumulated = 0
        for month in months:
            month_days = max(1, month.get("days", 30))
            if day_of_year < days_accumulated + month_days:
                current_month = month
                day_of_month = day_of_year - days_accumulated + 1
                break
            days_accumulated += month_days

        month_name = current_month.get("name", "Unknown Month")
        season_name = current_month.get("season", "Unknown Season")
        day_ordinal = get_ordinal(day_of_month)

        return f"{weekday_name}, the {day_ordinal} of {month_name}, Year {year} ({season_name})"
        
    except Exception as error:
        logging.error(f"Failed to calculate calendar date: {error}")
        return f"Day {absolute_day}"
    
def get_month_and_season(absolute_day: int, calendar_settings: dict) -> tuple[str, str]:
    """
    Returns the (month_name, season_name) for a given absolute day.
    """
    if not calendar_settings or not calendar_settings.get("months"):
        return "Unknown Month", "Unknown Season"
        
    months = calendar_settings.get("months", [])
    total_days_in_year = sum(max(1, month.get("days", 30)) for month in months)
    
    if total_days_in_year <= 0:
        return "Unknown Month", "Unknown Season"
        
    day_of_year = (absolute_day - 1) % total_days_in_year
    days_accumulated = 0
    
    for month in months:
        month_days = max(1, month.get("days", 30))
        if day_of_year < days_accumulated + month_days:
            return month.get("name", "Unknown Month"), month.get("season", "Unknown Season")
        days_accumulated += month_days
        
    return "Unknown Month", "Unknown Season"

def generate_dynamic_temperature(season: str, weather: str) -> int:
    """
    Generates a logical Fahrenheit temperature based on the current season and weather.
    """
    season_lower = season.lower()
    weather_lower = weather.lower()
    
    # 1. Base temperature ranges per season
    if "winter" in season_lower: base_temp = random.randint(15, 35)
    elif "spring" in season_lower: base_temp = random.randint(45, 65)
    elif "summer" in season_lower: base_temp = random.randint(75, 95)
    elif "fall" in season_lower or "autumn" in season_lower: base_temp = random.randint(45, 65)
    else: base_temp = random.randint(50, 70) # Fallback if no season is defined
    
    # 2. Apply weather modifiers
    if "sun" in weather_lower or "clear" in weather_lower:
        base_temp += random.randint(5, 10)
    elif "rain" in weather_lower or "storm" in weather_lower:
        base_temp -= random.randint(5, 15)
    elif "snow" in weather_lower or "blizzard" in weather_lower or "ice" in weather_lower or "sleet" in weather_lower or "hail" in weather_lower:
        # Snow implies freezing, so cap it at 32F
        base_temp = min(base_temp, 32) - random.randint(0, 15)
    elif "cloud" in weather_lower or "overcast" in weather_lower:
        base_temp -= random.randint(0, 5)
        
    return base_temp

def get_calendar_grid_data(absolute_day: int, calendar_settings: dict) -> dict | None:
    """
    Calculates the exact grid parameters needed to draw a calendar month.
    
    Args:
        absolute_day (int): The current absolute day integer.
        calendar_settings (dict): The user's custom calendar settings.
        
    Returns:
        dict | None: A dictionary containing the year, month name, days in month, 
                     current day of the month, and the starting weekday offset.
                     Returns None if the calendar isn't set up.
    """
    if not calendar_settings:
        return None

    weekdays = calendar_settings.get("weekdays", [])
    months = calendar_settings.get("months", [])

    if not weekdays or not months:
        return None

    try:
        total_days_in_year = sum(max(1, month.get("days", 30)) for month in months)
        if total_days_in_year <= 0:
            return None

        year = ((absolute_day - 1) // total_days_in_year) + 1
        day_of_year = (absolute_day - 1) % total_days_in_year

        current_month = months[0]
        day_of_month = day_of_year + 1

        days_accumulated = 0
        for month in months:
            month_days = max(1, month.get("days", 30))
            if day_of_year < days_accumulated + month_days:
                current_month = month
                day_of_month = day_of_year - days_accumulated + 1
                break
            days_accumulated += month_days

        # Calculate the absolute day integer for the 1st of THIS month
        absolute_day_of_first = absolute_day - day_of_month + 1
        
        # Calculate which weekday index the 1st lands on (0 = first day of week)
        start_weekday_index = (absolute_day_of_first - 1) % len(weekdays)

        return {
            "year": year,
            "month_name": current_month.get("name", "Unknown"),
            "season": current_month.get("season", "Unknown"),
            "month_total_days": max(1, current_month.get("days", 30)),
            "current_day": day_of_month,
            "start_offset": start_weekday_index,
            "weekdays": weekdays
        }
        
    except Exception as error:
        logging.error(f"Failed to calculate calendar grid data: {error}")
        return None
    
def get_ordinal(n: int) -> str:
    """
    Converts an integer into its ordinal string representation (e.g., 1 -> 1st, 2 -> 2nd).
    """
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{['th', 'st', 'nd', 'rd', 'th', 'th', 'th', 'th', 'th', 'th'][n % 10]}"