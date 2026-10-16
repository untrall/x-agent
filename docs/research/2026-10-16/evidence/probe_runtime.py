"""Disposable feasibility probe; not X-Agent product code. No model/API key used."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TypedDict


class State(TypedDict):
    session_id: str
    profile_version: int
    status: str
    answer: str


def checkpoint_phase(path: str, phase: str):
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import interrupt, Command
    from langgraph.checkpoint.sqlite import SqliteSaver

    def clarify(state):
        answer = interrupt({"question": "Can your partner join in 90 days?"})
        return {"answer": answer, "profile_version": state["profile_version"] + 1,
                "status": "renegotiating"}

    builder = StateGraph(State)
    builder.add_node("clarify", clarify)
    builder.add_edge(START, "clarify")
    builder.add_edge("clarify", END)
    config = {"configurable": {"thread_id": "cofounder-session-1"}}
    with SqliteSaver.from_conn_string(path) as saver:
        graph = builder.compile(checkpointer=saver)
        if phase == "pause":
            result = graph.invoke({"session_id": "s-1", "profile_version": 1,
                                   "status": "negotiating", "answer": ""}, config)
            assert result["__interrupt__"]
            assert graph.get_state(config).next == ("clarify",)
            print(json.dumps({"phase": "paused", "session_id": "s-1", "version": 1}))
        else:
            assert graph.get_state(config).values["session_id"] == "s-1"
            result = graph.invoke(Command(resume="yes, if AI product experience"), config)
            assert result["profile_version"] == 2
            assert result["session_id"] == "s-1"
            assert result["status"] == "renegotiating"
            print(json.dumps({"phase": "resumed_in_new_process", "result": result}))


def a2a_probe():
    import uuid
    from starlette.applications import Starlette
    from starlette.testclient import TestClient
    from a2a.helpers import new_task_from_user_message, new_text_message, new_text_part
    from a2a.server.agent_execution import AgentExecutor
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
    from a2a.types import AgentCard, AgentCapabilities, AgentInterface, AgentSkill, TaskState

    class ClarifyingAgent(AgentExecutor):
        async def execute(self, context, event_queue):
            task = context.current_task
            if task is None:
                task = new_task_from_user_message(context.message)
                await event_queue.enqueue_event(task)
            updater = TaskUpdater(event_queue=event_queue, task_id=task.id,
                                  context_id=task.context_id)
            if context.current_task is None:
                await updater.update_status(TaskState.TASK_STATE_INPUT_REQUIRED,
                                             message=new_text_message("Can you wait 90 days?"))
            else:
                await updater.add_artifact(parts=[new_text_part("agreed conditions")])
                await updater.update_status(TaskState.TASK_STATE_COMPLETED)

        async def cancel(self, context, event_queue):
            raise NotImplementedError

    card = AgentCard(name="Research probe", description="Bounded negotiation probe",
        version="0.1.0", capabilities=AgentCapabilities(),
        default_input_modes=["text/plain"], default_output_modes=["text/plain"],
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC",
            protocol_version="1.0", url="http://testserver/")],
        skills=[AgentSkill(id="negotiate", name="Negotiate", description="Clarify and resume",
                          tags=["negotiation"])])
    handler = DefaultRequestHandler(agent_executor=ClarifyingAgent(),
        task_store=InMemoryTaskStore(), agent_card=card)
    app = Starlette(routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")])
    with TestClient(app) as client:
        headers = {"A2A-Version": "1.0"}
        response = client.get("/.well-known/agent-card.json", headers=headers)
        assert response.status_code == 200, response.text

        def send(text, task_id=None, context_id=None):
            message = {"messageId": str(uuid.uuid4()), "role": "ROLE_USER",
                       "parts": [{"text": text}]}
            if task_id:
                message.update(taskId=task_id, contextId=context_id)
            response = client.post("/", headers=headers, json={"jsonrpc": "2.0", "id": "1",
                "method": "SendMessage", "params": {"message": message}})
            data = response.json()
            assert "error" not in data, data
            return data["result"]["task"]

        first = send("start")
        assert first["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", first
        second = send("yes", first["id"], first["contextId"])
        assert second["id"] == first["id"], second
        assert second["contextId"] == first["contextId"]
        assert second["status"]["state"] == "TASK_STATE_COMPLETED", second
        assert second["artifacts"]
        print(json.dumps({"probe": "A2A ASGI JSON-RPC roundtrip", "card": "ok",
            "states": [first["status"]["state"], second["status"]["state"]],
            "same_task_and_context": True, "artifact": True}))


if __name__ == "__main__":
    if len(sys.argv) == 3:
        checkpoint_phase(sys.argv[1], sys.argv[2])
    else:
        with tempfile.TemporaryDirectory() as tmp:
            for phase in ("pause", "resume"):
                subprocess.run([sys.executable, __file__, str(Path(tmp) / "checkpoint.sqlite"), phase], check=True)
        a2a_probe()
