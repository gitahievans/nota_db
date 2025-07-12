import subprocess
import os
import logging
import zipfile
import tempfile
import shutil
import psutil
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Tuple
from django.conf import settings
from django.core.cache import cache
import traceback

logger = logging.getLogger(__name__)

AUDIVERIS_HOME = "/app/audiveris"


# Configuration for dynamic resource allocation
class ResourceConfig:
    def __init__(self):
        self.total_memory_gb = psutil.virtual_memory().total // (1024**3)
        self.available_cores = psutil.cpu_count()
        self.max_concurrent_jobs = getattr(settings, "MAX_CONCURRENT_AUDIVERIS_JOBS", 2)

    def get_memory_allocation(self) -> str:
        """Dynamically allocate memory based on system load and concurrent jobs"""
        # Get current number of running jobs from cache
        running_jobs = cache.get("audiveris_running_jobs", 0)

        # Base memory allocation (minimum 1GB, maximum 2.5GB)
        base_memory = min(
            2.5, max(1.0, (self.total_memory_gb * 0.6) / max(1, running_jobs))
        )

        return f"-Xmx{int(base_memory * 1024)}m"


@contextmanager
def job_tracking():
    """Context manager to track concurrent jobs"""
    try:
        # Increment running jobs counter
        current_jobs = cache.get("audiveris_running_jobs", 0)
        cache.set("audiveris_running_jobs", current_jobs + 1, timeout=3600)
        yield
    finally:
        # Decrement running jobs counter
        current_jobs = cache.get("audiveris_running_jobs", 0)
        cache.set("audiveris_running_jobs", max(0, current_jobs - 1), timeout=3600)


@contextmanager
def temp_workspace(score_id: str):
    """Create and manage temporary workspace for processing"""
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix=f"audiveris_{score_id}_")
        logger.info(f"Created temporary workspace: {temp_dir}")
        yield temp_dir
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"Cleaned up temporary workspace: {temp_dir}")
            except Exception as e:
                logger.warning(
                    f"Failed to clean up temporary workspace {temp_dir}: {e}"
                )


def validate_file_size(file_path: str, max_size_mb: int = 50) -> None:
    """Validate file size before processing"""
    file_size = os.path.getsize(file_path)
    max_size_bytes = max_size_mb * 1024 * 1024

    if file_size > max_size_bytes:
        raise ValueError(
            f"File too large: {file_size / (1024*1024):.1f}MB. Maximum allowed: {max_size_mb}MB"
        )

    logger.info(f"File size validation passed: {file_size / (1024*1024):.1f}MB")


def get_optimized_image_options(file_ext: str) -> list:
    """Get optimized image processing options based on file type"""
    base_options = [
        "-option,org.audiveris.omr.sheet.Scale.targetInterline=20",
        "-option,org.audiveris.omr.sheet.Scale.minInterline=12",
        "-option,org.audiveris.omr.text.tesseract.TesseractOCR.useOCR=true",
        "-option,org.audiveris.omr.classifier.SampleRepository.useRepository=true",
    ]

    # Adjust image size limits based on available memory
    config = ResourceConfig()
    if config.total_memory_gb >= 4:
        max_dimension = 8192
    else:
        max_dimension = 6144

    image_limits = [
        f"-option,org.audiveris.omr.image.ImageFormatException.maxImageWidth={max_dimension}",
        f"-option,org.audiveris.omr.image.ImageFormatException.maxImageHeight={max_dimension}",
        f"-option,org.audiveris.omr.sheet.Sheet.maxSheetWidth={max_dimension}",
        f"-option,org.audiveris.omr.sheet.Sheet.maxSheetHeight={max_dimension}",
    ]

    return base_options + image_limits


def build_audiveris_command(input_path: str, output_path: str, file_ext: str) -> list:
    """Build optimized Audiveris command with dynamic resource allocation"""
    config = ResourceConfig()

    # Base command arguments
    cmd_args = f"-batch,-export,-output,{output_path}"

    # Add image-specific parameters for better recognition
    if file_ext.lower() in ["jpg", "jpeg", "png", "tiff", "tif"]:
        image_options = get_optimized_image_options(file_ext)
        cmd_args += "," + ",".join(image_options)

    cmd_args += f",{input_path}"

    # Build final command with dynamic memory allocation
    memory_setting = config.get_memory_allocation()

    return [
        "/opt/gradle-8.7/bin/gradle",
        "run",
        f"-PjvmLineArgs={memory_setting}",
        f"-PcmdLineArgs={cmd_args}",
    ]


def extract_xml_from_mxl(mxl_path: str, output_xml_path: str) -> None:
    """Efficiently extract XML from MXL file"""
    try:
        with zipfile.ZipFile(mxl_path, "r") as mxl_zip:
            file_list = mxl_zip.namelist()

            # Find XML files (prefer root level files)
            xml_files = [f for f in file_list if f.endswith(".xml") and "/" not in f]
            if not xml_files:
                xml_files = [f for f in file_list if f.endswith(".xml")]

            if not xml_files:
                raise Exception("No XML file found in MXL archive")

            xml_filename = xml_files[0]
            logger.info(f"Extracting XML file: {xml_filename}")

            # Direct extraction without intermediate steps
            mxl_zip.extract(xml_filename, os.path.dirname(output_xml_path))

            # Rename to expected output name if needed
            extracted_path = os.path.join(
                os.path.dirname(output_xml_path), xml_filename
            )
            if extracted_path != output_xml_path:
                os.rename(extracted_path, output_xml_path)

    except Exception as e:
        logger.error(f"Failed to extract XML from MXL: {str(e)}")
        raise


def process_with_audiveris(
    score_id: str, file_ext: str, input_path: str
) -> Tuple[str, Optional[str]]:
    """
    Optimized Audiveris processing with resource management and improved error handling
    """
    # Validate Audiveris directory
    if not os.path.exists(AUDIVERIS_HOME):
        logger.error(f"Audiveris directory {AUDIVERIS_HOME} does not exist")
        raise FileNotFoundError(f"Audiveris directory {AUDIVERIS_HOME} does not exist")

    # Validate input file
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file {input_path} does not exist")

    # Validate file size before processing
    validate_file_size(input_path)

    logger.info(f"Starting optimized Audiveris processing for score {score_id}")

    with job_tracking(), temp_workspace(score_id) as temp_dir:
        # Set up paths
        mxl_output_path = os.path.join(temp_dir, "output.mxl")
        xml_output_path = os.path.join(temp_dir, "output.xml")

        # Build optimized command
        audiveris_cmd = build_audiveris_command(input_path, temp_dir, file_ext)

        try:
            logger.info(
                f"Running optimized Audiveris command: {' '.join(audiveris_cmd)}"
            )

            # Run with adaptive timeout based on file size
            file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
            timeout = min(600, max(450, int(file_size_mb * 10)))

            result = subprocess.run(
                audiveris_cmd,
                check=True,
                capture_output=True,
                text=True,
                cwd=AUDIVERIS_HOME,
                timeout=timeout,
            )

            logger.info(f"Audiveris processing completed successfully")
            if result.stderr:
                logger.warning(f"Audiveris stderr: {result.stderr}")

        except subprocess.TimeoutExpired:
            logger.error(f"Audiveris processing timed out for score {score_id}")
            raise Exception(
                f"Processing timed out after {timeout} seconds. "
                "File may be too complex or large for current system resources."
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Audiveris failed with return code {e.returncode}")
            logger.error(f"Stderr: {e.stderr}")

            # Enhanced error handling with specific messages
            if "too low interline value" in str(e.stderr):
                raise Exception(
                    "Image resolution too low for music recognition. "
                    "Please upload a higher resolution image (recommended: 300 DPI or higher)"
                )
            elif (
                "Could not export since transcription did not complete successfully"
                in str(e.stderr)
            ):
                raise Exception(
                    "Music recognition failed. Please ensure the image contains clear, "
                    "well-lit sheet music with good contrast"
                )
            elif "OutOfMemoryError" in str(e.stderr):
                raise Exception(
                    "Insufficient memory to process this file. "
                    "Please try again later or reduce image size"
                )
            else:
                raise Exception(
                    f"Audiveris processing failed: {str(e.stderr)[:200]}..."
                )

        # Find generated MXL file
        mxl_files = [f for f in os.listdir(temp_dir) if f.endswith(".mxl")]
        if not mxl_files:
            all_files = os.listdir(temp_dir)
            logger.error(
                f"No MusicXML files generated. Files in temp directory: {all_files}"
            )
            raise Exception(
                "No MusicXML files generated. This usually means the image quality "
                "is insufficient for music recognition."
            )

        temp_mxl_path = os.path.join(temp_dir, mxl_files[0])

        # Validate generated file
        mxl_size = os.path.getsize(temp_mxl_path)
        if mxl_size < 100:
            raise Exception(f"Generated MusicXML file is too small ({mxl_size} bytes)")

        logger.info(f"Generated MusicXML file: {mxl_files[0]} ({mxl_size} bytes)")

        # Prepare final output paths
        final_mxl_path = settings.TEMP_STORAGE_DIR / f"{score_id}" / "output.mxl"
        final_xml_path = settings.TEMP_STORAGE_DIR / f"{score_id}" / "output.xml"

        # Ensure output directory exists
        os.makedirs(os.path.dirname(final_mxl_path), exist_ok=True)

        # Move MXL file to final location
        shutil.move(temp_mxl_path, final_mxl_path)

        # Extract XML for API serving
        try:
            extract_xml_from_mxl(str(final_mxl_path), str(final_xml_path))
            logger.info(f"Created XML file for serving at: {final_xml_path}")
        except Exception as e:
            logger.error(f"Failed to create XML file for serving: {str(e)}")
            final_xml_path = None

        # Copy to output directory for compatibility
        try:
            output_dir = Path(settings.BASE_DIR) / "output"
            output_dir.mkdir(exist_ok=True)
            destination_path = output_dir / f"output_{score_id}.xml"

            if final_xml_path and os.path.exists(final_xml_path):
                shutil.copy2(final_xml_path, destination_path)
                logger.info(f"Successfully copied XML file to: {destination_path}")
            else:
                # Fallback: extract directly to destination
                extract_xml_from_mxl(str(final_mxl_path), str(destination_path))
                logger.info(f"Successfully extracted XML file to: {destination_path}")

        except Exception as e:
            logger.error(f"Failed to copy XML file to output directory: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")

    return str(final_mxl_path), str(final_xml_path) if final_xml_path else None
