"""
Dataset downloader for Transfer ROI Rankings.

Downloads the "davidcariboo/player-scores" dataset from Kaggle via kagglehub.
Provides a cached wrapper so the pipeline only re-downloads when needed.
"""

import logging
from pathlib import Path

import kagglehub

from src.config import (
    KAGGLE_DATASET,
    RAW_DIR,
    CLEAN_DIR,
    CLEANED_PAIRS,
    CLEANED_CLUB_STATS,
)

logger = logging.getLogger(__name__)


def dataset_exists() -> bool:
    """
    Check if cleaned CSVs already exist on disk.
    If they do, we can skip the full pipeline re-run.
    """
    return CLEANED_PAIRS.exists() and CLEANED_CLUB_STATS.exists()


def download_dataset() -> Path:
    """
    Download the Kaggle dataset via kagglehub.

    Returns
    -------
    Path
        The path to the directory containing the raw CSV files.
    """
    logger.info("Downloading dataset '%s' via kagglehub ...", KAGGLE_DATASET)
    path = kagglehub.dataset_download(KAGGLE_DATASET)

    download_path = Path(path)
    logger.info("Dataset downloaded to %s", download_path)

    # Optionally symlink / copy to RAW_DIR for easy reference
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Raw data available at %s", RAW_DIR)

    return download_path


def list_raw_files(download_path: Path) -> list[Path]:
    """
    List all CSV files in the downloaded dataset directory.

    Parameters
    ----------
    download_path : Path
        Directory returned by kagglehub.dataset_download().

    Returns
    -------
    list[Path]
        Sorted list of CSV file paths.
    """
    files = sorted(download_path.glob("*.csv*"))  # handles .csv and .csv.gz
    logger.info("Found %d raw data files in %s", len(files), download_path)
    for f in files:
        logger.info("  - %s", f.name)
    return files


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    if dataset_exists():
        logger.info("Cleaned data already exists at %s  skipping download.", CLEAN_DIR)
    else:
        raw_path = download_dataset()
        list_raw_files(raw_path)
        logger.info("Download complete. Run `python -m src.clean` to process the data.")
