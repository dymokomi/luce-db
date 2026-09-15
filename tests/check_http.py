"""Concurrent, independent HTTP clients; loopback fixture only."""
from concurrent.futures import ThreadPoolExecutor
import http.client
from pathlib import Path
import subprocess
import tempfile

from check_journal import line
from check_checkpoint import decode


def check(executable):
    with tempfile.TemporaryDirectory(prefix="luce-db-http-") as tmp:
        path = Path(tmp) / "registry.db"
        for restart in range(2):
            process = subprocess.Popen([str(executable), str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                ready = line(process)
                assert ready.startswith("READY "), ready
                port = int(ready.split()[1])

                def request(method, route):
                    client = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
                    try:
                        client.request(method, route, body=b"")
                        response = client.getresponse()
                        return response.status, response.read().decode()
                    finally:
                        client.close()

                if restart == 0:
                    assert request("POST", "/claim/INVALID")[0] == 400
                    with ThreadPoolExecutor(max_workers=32) as pool:
                        claims = [pool.submit(request, "POST", f"/claim/user{i}") for i in range(32)]
                        checkpoints = [pool.submit(request, "POST", "/checkpoint") for _ in range(4)]
                        responses = [future.result() for future in claims]
                        for future in checkpoints:
                            code, checkpoint_generation = future.result()
                            assert code == 200 and int(checkpoint_generation) in (1, 2)
                    assert [status for status, _ in responses].count(201) == 1, responses
                    assert [status for status, _ in responses].count(409) == 31, responses
                else:
                    assert request("POST", "/claim/late")[0] == 409
                status, state = request("GET", "/state")
                generation, count, peak = map(int, state.split())
                assert status == 200 and generation == 2 and count == 2
                if restart == 0: assert peak >= 2, "application handlers never overlapped"
                assert request("POST", "/checkpoint") == (200, "2")
                assert request("POST", "/stop")[0] == 200
                stdout, stderr = process.communicate(timeout=15)
                assert process.returncode == 0, (stdout, stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=10)
        generation, state, end = decode(path.read_bytes())
        assert end == path.stat().st_size
        users = [key for key in state if key.startswith(b"user/")]
        assert len(users) == 1 and state[b"audit/registration"] == state[users[0]]
        assert b"invite/test-only" not in state and generation == 2
        print("PASS HTTP: 32 competing claims, one winner, overlapping workers, atomic audit, concurrent checkpoints, restart", flush=True)
