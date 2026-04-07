import re

with open('src/ui/api/routes.py', 'r') as f:
    content = f.read()

divergence_trend = """
@router.get("/grading/divergence-trend", tags=["grading"])
def get_divergence_trend(current_user: Annotated[UserInfo, Depends(require_auth)]):
    \"\"\"
    Returns average divergence scores over time.
    \"\"\"
    from grading import get_human_grading_interface
    interface = get_human_grading_interface()
    # Ensure initialized
    interface.get_next_session()

    sessions = interface.storage.sessions.values()

    # Simple aggregation by date (YYYY-MM-DD)
    trends = {}
    for session in sessions:
        if session.status.value == "COMPLETED" and session.divergence_analysis:
            # We want just the date part of the ISO string
            date = session.created_at[:10]
            score = session.divergence_analysis.overall_divergence
            if date not in trends:
                trends[date] = {"date": date, "sum": 0, "count": 0}
            trends[date]["sum"] += score
            trends[date]["count"] += 1

    result = []
    for date, data in sorted(trends.items()):
        result.append({
            "date": date,
            "avg_divergence": round(data["sum"] / data["count"], 2),
            "sessions": data["count"]
        })

    return {"trend": result}

"""

if "def get_divergence_trend" not in content:
    # Append to the end
    content += divergence_trend

with open('src/ui/api/routes.py', 'w') as f:
    f.write(content)
