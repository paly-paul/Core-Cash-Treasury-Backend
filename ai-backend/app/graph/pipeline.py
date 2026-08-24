from langgraph.graph import StateGraph

from app.graph.state import AgentState
from app.agents.daily_cash_position import run_agent_1_cash_position
from app.agents.liquidity_risk import run_agent_3_liquidity_risk
from app.agents.action_recommendation import run_agent_4_recommendations
from app.agents.policy_control import PolicyControlAgent, write_recommendations_to_mongo


async def run_agent_2_forecast(state: AgentState) -> AgentState:
    state["errors"]["agent_2"] = "NOT_IMPLEMENTED"
    return state


async def run_agent_5_variance(state: AgentState) -> AgentState:
    state["errors"]["agent_5"] = "NOT_IMPLEMENTED"
    return state


async def run_agent_6_cfo_summary(state: AgentState) -> AgentState:
    state["errors"]["agent_6"] = "NOT_IMPLEMENTED"
    return state


async def run_agent_7_continuity(state: AgentState) -> AgentState:
    state["errors"]["agent_7"] = "NOT_IMPLEMENTED"
    return state


async def run_agent_8_policy_control(state: AgentState) -> AgentState:
    """Run Policy Control Agent — validates and filters recommendations."""
    try:
        from app.mongo.client import get_mongo_db

        raw = state.get("action_recommendations", {}).get("raw", [])
        agent = PolicyControlAgent()
        approved, blocked = agent.run(raw)

        # Write only approved recommendations to MongoDB
        mongo = get_mongo_db()
        result_id = await write_recommendations_to_mongo(
            mongo_db=mongo,
            client_id=state["client_id"],
            job_id=state["job_id"],
            approved_recs=approved,
            blocked_recs=blocked,
            agent1_run_id=state.get("cash_position", {}).get("_id", ""),
            agent3_run_id=state.get("liquidity_risk", {}).get("_id", ""),
        )

        state["action_recommendations"] = {
            "result_id": result_id,
            "recommendation_count": len(approved),
            "blocked_count": len(blocked),
            "status": "completed",
        }
        return state

    except Exception as e:
        state["errors"]["agent_8"] = str(e)
        return state


def build_pipeline():
    """Build compiled LangGraph pipeline with 8 stub nodes.

    Sequential MVP execution order:
      agent_1_cash_position
        → agent_3_liquidity_risk
        → agent_2_forecast
        → agent_4_recommendations
        → agent_8_policy_control
        → agent_5_variance
        → agent_7_continuity
        → agent_6_cfo_summary
        → END
    """
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("agent_1_cash_position", run_agent_1_cash_position)
    graph.add_node("agent_2_forecast", run_agent_2_forecast)
    graph.add_node("agent_3_liquidity_risk", run_agent_3_liquidity_risk)
    graph.add_node("agent_4_recommendations", run_agent_4_recommendations)
    graph.add_node("agent_5_variance", run_agent_5_variance)
    graph.add_node("agent_6_cfo_summary", run_agent_6_cfo_summary)
    graph.add_node("agent_7_continuity", run_agent_7_continuity)
    graph.add_node("agent_8_policy_control", run_agent_8_policy_control)

    # Set entry point
    graph.set_entry_point("agent_1_cash_position")

    # Wire edges in sequential order
    graph.add_edge("agent_1_cash_position", "agent_3_liquidity_risk")
    graph.add_edge("agent_3_liquidity_risk", "agent_2_forecast")
    graph.add_edge("agent_2_forecast", "agent_4_recommendations")
    graph.add_edge("agent_4_recommendations", "agent_8_policy_control")
    graph.add_edge("agent_8_policy_control", "agent_5_variance")
    graph.add_edge("agent_5_variance", "agent_7_continuity")
    graph.add_edge("agent_7_continuity", "agent_6_cfo_summary")
    graph.set_finish_point("agent_6_cfo_summary")

    return graph.compile()


pipeline = build_pipeline()
