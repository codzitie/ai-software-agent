"""Terminal chat loop."""
from src.chat.session import ChatSession
from src.utils.errors import AgentError
from src.utils.logging import setup_logging
from src.utils.trace import instrument_tools

HELP = """Commands:
  /repo <path>   set the repository to work on
  /resume        continue an interrupted run
  /thread        show the current thread id
  /new           start a fresh thread
  /help          show this help
  /exit          quit
Press Ctrl+C during a run to stop it (progress is saved)."""


def _progress(node: str) -> None:
    print(f"  · {node}", flush=True)

def _confirm(payload: dict) -> bool:
    print("\nThe agent wants to install packages:")
    for pkg in payload.get("packages", []):
        print(f"  - {pkg}")
    print(f"Reason:  {payload.get('reason', '')}")
    print(f"Project: {payload.get('repo', '')}")
    while True:
        answer = input("Install? [y/n]> ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


def _drive(session: ChatSession, first_reply: str) -> None:
    """Show the reply, or keep asking for confirmations until the run finishes."""
    reply = first_reply
    while payload := session.pending_interrupt():
        try:
            approved = _confirm(payload)
        except (EOFError, KeyboardInterrupt):
            print("\nPaused. Type /resume to answer later.\n")
            return
        reply = session.answer(approved, on_step=_progress)
    if reply:
        print(f"\nagent> {reply}\n")

def run_cli(repo: str | None = None, thread_id: str | None = None) -> None:
    setup_logging()
    instrument_tools()
    session = ChatSession(thread_id)
    if repo:
        session.set_repo(repo)

    print(f"AI Software Agent  (thread {session.thread_id}, repo: {session.repo_path or 'not set'})")
    print("Type /help for commands.\n")

    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue

        if text.startswith("/"):
            cmd, _, arg = text.partition(" ")
            if cmd == "/exit":
                break
            elif cmd == "/help":
                print(HELP)
            elif cmd == "/thread":
                print(f"thread: {session.thread_id}")
            elif cmd == "/new":
                session = ChatSession(repo=None) if False else ChatSession()
                print(f"new thread: {session.thread_id} (set a repo with /repo)")
            elif cmd == "/repo":
                try:
                    print(f"repo set: {session.set_repo(arg.strip())}")
                except AgentError as exc:
                    print(f"Error: {exc}")
            elif cmd == "/resume":
                _drive(session, session.resume(on_step=_progress))
            else:
                print("Unknown command. Type /help.")
            continue

        _drive(session, session.send(text, on_step=_progress))