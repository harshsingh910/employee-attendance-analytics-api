"""
Analytics and Aggregation Pipelines Repository
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import json_util
from pymongo.database import Database

from app.db.mongodb import get_database


class AnalyticsRepository:
    def __init__(self, db: Optional[Database] = None):
        self._db = db

    @property
    def db(self) -> Database:
        return self._db if self._db is not None else get_database()

    def aggregate_employee_monthly(
        self, emp_code: str, first_day: str, last_day: str
    ) -> Optional[Dict[str, Any]]:
        pipeline: List[Dict[str, Any]] = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {"$gte": first_day, "$lte": last_day},
                }
            },
            {
                "$project": {
                    "status": 1,
                    "late_minutes": {"$ifNull": ["$late_minutes", 0]},
                    "overtime_minutes": {"$ifNull": ["$overtime_minutes", 0]},
                    "half_day": {"$ifNull": ["$half_day", False]},
                    "day_of_week": {
                        "$dayOfWeek": {
                            "$dateFromString": {"dateString": "$date"}
                        }
                    },
                }
            },
            {
                "$group": {
                    "_id": None,
                    "present_days": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$in": ["$day_of_week", [2, 3, 4, 5, 6]]},  # Mon-Fri
                                        {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                    ]
                                },
                                {"$cond": ["$half_day", 0.5, 1.0]},
                                0.0,
                            ]
                        }
                    },
                    "leave_days": {
                        "$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}
                    },
                    "late_count": {
                        "$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}
                    },
                    "total_late_minutes": {"$sum": "$late_minutes"},
                    "total_overtime_minutes": {"$sum": "$overtime_minutes"},
                }
            },
        ]
        res = list(self.db.attendance_logs.aggregate(pipeline))
        return res[0] if res else None

    def aggregate_department_summary(
        self, first_day: str, last_day: str, department: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        match_stage: Dict[str, Any] = {"joined_on": {"$lte": last_day}}
        if department:
            match_stage["department"] = department

        pipeline = [
            {"$match": match_stage},
            {
                "$lookup": {
                    "from": "attendance_logs",
                    "let": {"emp": "$emp_code"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$emp_code", "$$emp"]},
                                        {"$gte": ["$date", first_day]},
                                        {"$lte": ["$date", last_day]},
                                    ]
                                }
                            }
                        }
                    ],
                    "as": "logs",
                }
            },
            {
                "$addFields": {
                    "emp_present_days": {
                        "$sum": {
                            "$map": {
                                "input": "$logs",
                                "as": "log",
                                "in": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$in": ["$$log.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                                {
                                                    "$in": [
                                                        {
                                                            "$dayOfWeek": {
                                                                "$dateFromString": {"dateString": "$$log.date"}
                                                            }
                                                        },
                                                        [2, 3, 4, 5, 6],
                                                    ]
                                                },
                                            ]
                                        },
                                        {"$cond": [{"$eq": ["$$log.half_day", True]}, 0.5, 1.0]},
                                        0.0,
                                    ]
                                },
                            }
                        }
                    },
                    "emp_work_hours_sum": {
                        "$sum": {
                            "$map": {
                                "input": {
                                    "$filter": {
                                        "input": "$logs",
                                        "as": "log",
                                        "cond": {
                                            "$and": [
                                                {"$in": ["$$log.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                                {"$ne": ["$$log.work_hours", None]},
                                            ]
                                        },
                                    }
                                },
                                "as": "log",
                                "in": "$$log.work_hours",
                            }
                        }
                    },
                    "emp_work_hours_count": {
                        "$size": {
                            "$filter": {
                                "input": "$logs",
                                "as": "log",
                                "cond": {
                                    "$and": [
                                        {"$in": ["$$log.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                        {"$ne": ["$$log.work_hours", None]},
                                    ]
                                },
                            }
                        }
                    },
                    "emp_late_count": {
                        "$size": {
                            "$filter": {
                                "input": "$logs",
                                "as": "log",
                                "cond": {"$gt": [{"$ifNull": ["$$log.late_minutes", 0]}, 0]},
                            }
                        }
                    },
                    "emp_total_late_minutes": {
                        "$sum": {
                            "$map": {
                                "input": "$logs",
                                "as": "log",
                                "in": {"$ifNull": ["$$log.late_minutes", 0]},
                            }
                        }
                    },
                    "emp_leave_count": {
                        "$size": {
                            "$filter": {
                                "input": "$logs",
                                "as": "log",
                                "cond": {"$eq": ["$$log.status", "LEAVE"]},
                            }
                        }
                    },
                    "emp_on_duty_count": {
                        "$size": {
                            "$filter": {
                                "input": "$logs",
                                "as": "log",
                                "cond": {"$eq": ["$$log.status", "ON_DUTY"]},
                            }
                        }
                    },
                }
            },
            {
                "$group": {
                    "_id": "$department",
                    "headcount": {"$sum": 1},
                    "present_days": {"$sum": "$emp_present_days"},
                    "total_work_hours": {"$sum": "$emp_work_hours_sum"},
                    "work_hours_count": {"$sum": "$emp_work_hours_count"},
                    "late_count": {"$sum": "$emp_late_count"},
                    "total_late_minutes": {"$sum": "$emp_total_late_minutes"},
                    "leave_count": {"$sum": "$emp_leave_count"},
                    "on_duty_count": {"$sum": "$emp_on_duty_count"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        return list(self.db.employees.aggregate(pipeline))

    def aggregate_late_leaderboard(
        self, first_day: str, last_day: str, limit: int, department: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        pipeline: List[Dict[str, Any]] = [
            {
                "$match": {
                    "date": {"$gte": first_day, "$lte": last_day},
                    "late_minutes": {"$gt": 0},
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {"$sum": "$late_minutes"},
                    "late_count": {"$sum": 1},
                }
            },
            {
                "$lookup": {
                    "from": "employees",
                    "localField": "_id",
                    "foreignField": "emp_code",
                    "as": "emp",
                }
            },
            {"$unwind": "$emp"},
        ]

        if department:
            pipeline.append({"$match": {"emp.department": department}})

        # Standard competition ranking: ties share rank, next rank skipped
        pipeline.extend([
            {
                "$setWindowFields": {
                    "sortBy": {"total_late_minutes": -1},
                    "output": {
                        "rank": {"$rank": {}}
                    },
                }
            },
            {"$match": {"rank": {"$lte": limit}}},
            {"$sort": {"total_late_minutes": -1, "_id": 1}},
            {
                "$project": {
                    "_id": 0,
                    "rank": 1,
                    "emp_code": "$_id",
                    "name": "$emp.name",
                    "department": "$emp.department",
                    "total_late_minutes": 1,
                    "late_count": 1,
                }
            },
        ])
        return list(self.db.attendance_logs.aggregate(pipeline))

    def aggregate_department_trend(
        self,
        dept_emp_codes: List[str],
        dept_emps: List[Dict[str, Any]],
        from_date: str,
        to_date: str,
        from_dt: datetime,
        to_dt_plus_1: datetime,
    ) -> List[Dict[str, Any]]:
        pipeline: List[Dict[str, Any]] = [
            {
                "$match": {
                    "emp_code": {"$in": dept_emp_codes},
                    "date": {"$gte": from_date, "$lte": to_date},
                }
            },
            {
                "$group": {
                    "_id": "$date",
                    "present_count": {
                        "$sum": {
                            "$cond": [
                                {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                {"$cond": ["$half_day", 0.5, 1.0]},
                                0.0,
                            ]
                        }
                    },
                    "late_count": {
                        "$sum": {
                            "$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]
                        }
                    },
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "date": "$_id",
                    "date_dt": {"$dateFromString": {"dateString": "$_id"}},
                    "present_count": 1,
                    "late_count": 1,
                }
            },
            {
                "$densify": {
                    "field": "date_dt",
                    "range": {
                        "step": 1,
                        "unit": "day",
                        "bounds": [from_dt, to_dt_plus_1],
                    },
                }
            },
            {
                "$project": {
                    "date": {
                        "$dateToString": {"format": "%Y-%m-%d", "date": "$date_dt"}
                    },
                    "present_count": {"$ifNull": ["$present_count", 0.0]},
                    "late_count": {"$ifNull": ["$late_count", 0]},
                }
            },
            {"$sort": {"date": 1}},
            {
                "$addFields": {
                    "is_working_day": {
                        "$in": [
                            {"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}},
                            [2, 3, 4, 5, 6],
                        ]
                    },
                    "headcount": {
                        "$size": {
                            "$filter": {
                                "input": dept_emps,
                                "as": "e",
                                "cond": {"$lte": ["$$e.joined_on", "$date"]},
                            }
                        }
                    },
                }
            },
            {
                "$addFields": {
                    "attendance_rate": {
                        "$cond": [
                            {
                                "$and": [
                                    "$is_working_day",
                                    {"$gt": ["$headcount", 0]},
                                ]
                            },
                            {
                                "$round": [
                                    {"$divide": ["$present_count", "$headcount"]},
                                    4,
                                ]
                            },
                            None,
                        ]
                    }
                }
            },
            {
                "$setWindowFields": {
                    "sortBy": {"date": 1},
                    "output": {
                        "moving_avg_7d": {
                            "$avg": "$attendance_rate",
                            "window": {
                                "documents": [-6, "current"]
                            },
                        }
                    },
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "date": 1,
                    "is_working_day": 1,
                    "headcount": 1,
                    "present_count": 1,
                    "late_count": 1,
                    "attendance_rate": 1,
                    "moving_avg_7d": {
                        "$cond": [
                            {"$ne": ["$moving_avg_7d", None]},
                            {"$round": ["$moving_avg_7d", 4]},
                            None,
                        ]
                    },
                }
            },
        ]
        return list(self.db.attendance_logs.aggregate(pipeline))

    def explain_command(self, collection_name: str, command: Dict[str, Any]) -> Dict[str, Any]:
        """Runs explain command on a database operation."""
        explain_cmd = {
            "explain": command,
            "verbosity": "executionStats",
        }
        res = self.db.command(explain_cmd)
        return json.loads(json_util.dumps(res))
