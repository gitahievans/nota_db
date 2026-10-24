"""Run once from cron, or as an independent container alongside web/worker."""
import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from files.lifecycle import recover_sessions


class Command(BaseCommand):
    help = "Recover abandoned analysis jobs and delete expired owned sessions (catalog/legacy excluded)."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--interval", type=int, default=60)

    def handle(self, *args, **options):
        while True:
            try:
                close_old_connections()
                self.stdout.write(str(recover_sessions()))
            except Exception as exc:
                if not options["loop"]:
                    raise
                self.stderr.write(f"Analysis recovery unavailable ({type(exc).__name__}); retrying.")
            if not options["loop"]:
                return
            time.sleep(max(1, options["interval"]))
