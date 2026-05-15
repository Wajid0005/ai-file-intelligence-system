import logging
import os

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok = True)

logging.basicConfig(
        filename = "logs/system.log",
        level= logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)