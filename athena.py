"""Run an isolated Athena book job, independently of a chat session."""
import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '16_Runtime'))
from job_runner import JobRunner, create_job, launch_worker
from providers import model_overrides


def main():
    parser = argparse.ArgumentParser(description='Athena autonomous manuscript worker')
    parser.add_argument('command', choices=['start', 'resume', 'status', 'ui'])
    parser.add_argument('--concept')
    parser.add_argument('--chapters', type=int)
    parser.add_argument('--job', help='Job ID printed by start')
    parser.add_argument('--background', action='store_true', help='Run detached; write worker.log')
    parser.add_argument('--provider', choices=['openrouter', 'lmstudio', 'ollama'])
    parser.add_argument('--model', help='Exact installed model ID (required with --provider)')
    parser.add_argument('--base-url', help='Local model server URL ending in /v1')
    parser.add_argument('--port', type=int, default=8765, help='Local web UI port')
    args = parser.parse_args()
    if args.command == 'ui':
        from web_ui import serve
        serve(ROOT, args.port)
        return
    if args.command != 'start' and (args.provider or args.model or args.base_url):
        parser.error('Model options apply only to start; resumed jobs use their saved config.')
    if args.command == 'start':
        if not args.concept:
            parser.error('start requires --concept')
        overrides = None
        if args.provider or args.model or args.base_url:
            overrides = model_overrides(args.provider or 'openrouter', args.model, args.base_url)
        job = create_job(ROOT, args.concept, args.chapters, overrides)
        print(f'Job: {job.name}', flush=True)
    else:
        if not args.job or not all(c in '0123456789abcdef' for c in args.job) or len(args.job) != 32:
            parser.error('Specify --job with the job ID printed by start')
        job = ROOT / 'jobs' / args.job
    if args.command == 'status':
        print((job / 'job.json').read_text(encoding='utf-8'))
        return
    if args.background:
        launch_worker(ROOT, job)
        print(f'Worker launched. Check: python athena.py status --job {job.name}')
        return
    asyncio.run(JobRunner(job).run())
    print(f'Manuscript completed: {job / "08_Memory" / "manuscript.md"}')


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print(f'Job stopped: {error}', file=sys.stderr)
        sys.exit(1)
