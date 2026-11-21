"""Desktop server: packaged resources, an allocated port, and parent shutdown."""
import asyncio
from contextlib import asynccontextmanager
import json
import multiprocessing
import os
import socket
import sys
import threading


def _external_library_paths() -> None:
    """Keep the bundled Python's libraries out of external CLI processes."""
    if not getattr(sys, "frozen", False):
        return
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    for key in ("LD_LIBRARY_PATH", "LIBPATH"):
        original = os.environ.pop(key + "_ORIG", None)
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original


def main() -> None:
    os.environ["MAC_PORT"] = "0"  # Each desktop instance owns its server port.
    os.environ["PYTHONIOENCODING"] = "utf-8"
    import config
    import main as web
    import uvicorn

    family = socket.AF_INET6 if ":" in config.HOST else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as listener:
        preferred_port = int(os.environ.get("BAIZE_DESKTOP_PORT", "0"))
        try:
            listener.bind((config.HOST, preferred_port))
        except OSError:
            if not preferred_port:
                raise
            listener.bind((config.HOST, 0))
        config.PORT = listener.getsockname()[1]
        web.PORT = config.PORT
        os.environ["MAC_PORT"] = str(config.PORT)
        original_lifespan = web.app.router.lifespan_context

        @asynccontextmanager
        async def desktop_lifespan(app):
            async with original_lifespan(app):
                yield
                web.orchestra.SHUTTING_DOWN["now"] = True
                running = list(web.tasks.values())
                for task in running:
                    task.cancel()
                if running:
                    await asyncio.gather(*running, return_exceptions=True)

        web.app.router.lifespan_context = desktop_lifespan
        server = uvicorn.Server(uvicorn.Config(
            web.app, host=config.HOST, port=config.PORT, loop="asyncio",
            http="h11", ws="websockets", lifespan="on", log_level="warning",
            timeout_graceful_shutdown=5,
        ))

        def parent_control():
            try:
                if sys.stdin:
                    for line in sys.stdin:
                        if line.strip() == "shutdown":
                            break
            finally:
                server.should_exit = True

        _external_library_paths()
        threading.Thread(target=parent_control, daemon=True).start()
        print("BAIZE_DESKTOP_READY " + json.dumps({"host": config.HOST, "port": config.PORT}), flush=True)
        server.run(sockets=[listener])


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
