"""Isolated browser fixture. Never writes to the user's book library."""
import json
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_audiobook import AudiobookTests, wav, audiobook, AthenaServer
import book_video


class SpeechStub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        body = wav(frames=24000)
        self.send_response(200)
        self.send_header('Content-Type', 'audio/wav')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


fixture = AudiobookTests()
fixture.setUp()
speech = ThreadingHTTPServer(('127.0.0.1', 0), SpeechStub)
threading.Thread(target=speech.serve_forever, daemon=True).start()
settings = {**audiobook.DEFAULTS, 'base_url': f'http://127.0.0.1:{speech.server_address[1]}/v1'}
from job_runner import atomic_json
atomic_json(fixture.root / 'config/narration.json', settings)


def launch(root, job):
    threading.Thread(target=audiobook.run, args=(job,), daemon=True).start()


def launch_film(root, job):
    threading.Thread(target=book_video.run, args=(job,), daemon=True).start()


server = AthenaServer(fixture.root, 8766, audio_launcher=launch, film_launcher=launch_film)
print(f'Studio fixture: http://127.0.0.1:8766/books/{fixture.job.name}/studio', flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
    speech.shutdown(); speech.server_close()
    fixture.tearDown()
