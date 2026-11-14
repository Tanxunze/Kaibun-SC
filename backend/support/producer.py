import calendar
from dataclasses import dataclass
@dataclass(frozen=True)
class Birthday:
    month: int
    day: int
def is_day_of_the_year(month, day):
    return 1 <= month <= 12 and 1 <= day <= calendar.monthrange(2000, month)[1]
