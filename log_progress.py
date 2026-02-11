import logging
import time

UPDATE_INTERVAL = 15


def print_progress(tasks, total_tasks=0, update_interval=UPDATE_INTERVAL):
    completed_tasks = 0
    start_time = time.time()
    last_update_time = start_time
    total_tasks = total_tasks if total_tasks else len(tasks)

    for future in tasks:
        yield future
        completed_tasks += 1
        current_time = time.time()
        if current_time - last_update_time >= update_interval:
            calculate_progress(completed_tasks, current_time, start_time, total_tasks)
            last_update_time = current_time


def calculate_progress(completed_tasks, current_time, start_time, total_tasks):
    progress_percentage = (completed_tasks / total_tasks) * 100
    elapsed_time = current_time - start_time
    avg_time_per_task = elapsed_time / completed_tasks if completed_tasks > 0 else 0
    remaining_tasks = total_tasks - completed_tasks
    estimated_remaining_time = avg_time_per_task * remaining_tasks
    logging.info(
        f"Progress: {completed_tasks}/{total_tasks} tasks completed "
        f"({progress_percentage:.2f}%). "
        f"Estimated remaining time: {estimated_remaining_time:.2f} seconds."
    )


def setup_logging():
    class ColorFormatter(logging.Formatter):
        COLORS = {
            'DEBUG': '\033[96m',  # Cyan
            'INFO': '\033[92m',  # Green
            'WARNING': '\033[93m',  # Yellow
            'ERROR': '\033[91m',  # Red
            'CRITICAL': '\033[95m',  # Magenta
        }
        RESET = '\033[0m'

        def format(self, record):
            log_color = self.COLORS.get(record.levelname, self.RESET)
            message = super().format(record)  # Используем стандартный форматтер
            return f"{log_color}{message}{self.RESET}"

    logger = logging.getLogger("")
    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter())

    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
