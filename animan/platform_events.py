"""Optional native lifecycle hooks. No platform imports in the shared engine."""
progress_handler = None
completed_handler = None


def progress(task):
    if progress_handler:
        progress_handler(task)


def completed(task):
    if completed_handler:
        completed_handler(task)
