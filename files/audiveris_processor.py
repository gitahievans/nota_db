import subprocess
import os
import logging
import zipfile
from django.conf import settings
import traceback

logger = logging.getLogger(__name__)

AUDIVERIS_HOME = "/app/audiveris"


def process_with_audiveris(score_id, file_ext, input_path):
    # Verify Audiveris directory
    audiveris_dir = AUDIVERIS_HOME
    if not os.path.exists(audiveris_dir):
        logger.error(f"Audiveris directory {audiveris_dir} does not exist")
        raise FileNotFoundError(f"Audiveris directory {audiveris_dir} does not exist")
    logger.info(f"Audiveris directory contents: {os.listdir(audiveris_dir)}")

    # Run Audiveris to convert file to MusicXML
    mxl_path = settings.TEMP_STORAGE_DIR / f"{score_id}"
    logger.info(f"Starting Audiveris processing for score {score_id}")

    # Build the command line arguments string for Audiveris
    cmd_args = f"-batch,-export,-output,{mxl_path}"

    # Add image-specific parameters for better recognition
    if file_ext.lower() in ["jpg", "jpeg", "png", "tiff", "tif"]:
        image_options = [
            "-option,org.audiveris.omr.sheet.Scale.targetInterline=20",
            "-option,org.audiveris.omr.sheet.Scale.minInterline=12",
            "-option,org.audiveris.omr.image.ImageFormatException.maxImageWidth=8192",
            "-option,org.audiveris.omr.image.ImageFormatException.maxImageHeight=8192",
            "-option,org.audiveris.omr.sheet.Sheet.maxSheetWidth=8192",
            "-option,org.audiveris.omr.sheet.Sheet.maxSheetHeight=8192",
            "-option,org.audiveris.omr.text.tesseract.TesseractOCR.useOCR=true",
            "-option,org.audiveris.omr.classifier.SampleRepository.useRepository=true",
        ]
        cmd_args += "," + ",".join(image_options)

    cmd_args += f",{input_path}"

    # Build final Audiveris command
    audiveris_cmd = [
        "/opt/gradle-8.7/bin/gradle",
        "run",
        "-PjvmLineArgs=-Xmx3g",
        f"-PcmdLineArgs={cmd_args}",
    ]

    try:
        logger.info(f"Running Audiveris command: {' '.join(audiveris_cmd)}")
        result = subprocess.run(
            audiveris_cmd,
            check=True,
            capture_output=True,
            text=True,
            cwd=audiveris_dir,
            timeout=300,
        )
        logger.info(f"Audiveris stdout: {result.stdout}")
        if result.stderr:
            logger.warning(f"Audiveris stderr: {result.stderr}")
        logger.info(f"Converted file to MusicXML at {mxl_path}")

    except subprocess.TimeoutExpired:
        logger.error(f"Audiveris processing timed out for score {score_id}")
        raise Exception(
            "Audiveris processing timed out - file may be too complex or large"
        )

    except subprocess.CalledProcessError as e:
        logger.error(f"Audiveris failed with return code {e.returncode}")
        logger.error(f"Audiveris stderr: {e.stderr}")
        logger.error(f"Audiveris stdout: {e.stdout}")
        if "too low interline value" in e.stderr:
            raise Exception(
                "Image resolution too low for music recognition. "
                "Please upload a higher resolution image (recommended: 300 DPI or higher)"
            )
        elif (
            "Could not export since transcription did not complete successfully"
            in e.stderr
        ):
            raise Exception(
                "Music recognition failed. Please ensure the image contains clear, "
                "well-lit sheet music with good contrast"
            )
        elif "OutOfMemoryError" in e.stderr:
            raise Exception(
                "Image too large to process. Please reduce image size or complexity"
            )
        else:
            raise Exception(f"Audiveris processing failed: {e.stderr}")

    # Find and validate MusicXML file
    mxl_files = [f for f in os.listdir(mxl_path) if f.endswith(".mxl")]
    if not mxl_files:
        all_files = os.listdir(mxl_path) if os.path.exists(mxl_path) else []
        logger.error(
            f"No MusicXML files generated. Files in output directory: {all_files}"
        )
        omr_files = [f for f in all_files if f.endswith(".omr")]
        if omr_files:
            logger.info(
                f"Found OMR files: {omr_files} - this suggests partial processing"
            )
        raise Exception(
            "No MusicXML files generated. This usually means the image quality "
            "is insufficient for music recognition or the image doesn't contain "
            "recognizable sheet music."
        )

    mxl_file = os.path.join(mxl_path, mxl_files[0])
    logger.info(f"Found MusicXML file: {mxl_file}")

    mxl_size = os.path.getsize(mxl_file)
    logger.info(f"MusicXML file size: {mxl_size} bytes")
    if mxl_size < 100:
        logger.error(f"Generated MusicXML file is too small ({mxl_size} bytes)")
        raise Exception("Generated MusicXML file appears to be empty or corrupt")

    # Rename to standard output name
    output_mxl_path = os.path.join(mxl_path, "output.mxl")
    try:
        os.rename(mxl_file, output_mxl_path)
        logger.info(f"Renamed MusicXML file to: {output_mxl_path}")
        if not os.path.exists(output_mxl_path):
            logger.error(f"Renamed file {output_mxl_path} does not exist after rename")
            raise Exception("Renamed MusicXML file does not exist")
    except Exception as e:
        logger.error(f"Failed to rename MusicXML file: {str(e)}")
        raise

    # Create XML version for serving via API
    xml_output_path = None
    try:
        xml_output_path = os.path.join(mxl_path, "output.xml")
        with zipfile.ZipFile(output_mxl_path, "r") as mxl_zip:
            file_list = mxl_zip.namelist()
            logger.info(f"Files in MXL for XML extraction: {file_list}")
            xml_files = [f for f in file_list if f.endswith(".xml") and "/" not in f]
            if not xml_files:
                xml_files = [f for f in file_list if f.endswith(".xml")]
            if not xml_files:
                raise Exception("No XML file found in MXL archive for serving")
            xml_filename = xml_files[0]
            logger.info(f"Extracting XML for serving: {xml_filename}")
            with mxl_zip.open(xml_filename) as xml_file:
                xml_content = xml_file.read()
                with open(xml_output_path, "wb") as output_file:
                    output_file.write(xml_content)
        logger.info(f"Created XML file for serving at: {xml_output_path}")
    except Exception as e:
        logger.error(f"Failed to create XML file for serving: {str(e)}")
        xml_output_path = None

    # Copy MusicXML to output directory
    try:
        output_dir = os.path.join(settings.BASE_DIR, "output")
        os.makedirs(output_dir, exist_ok=True)
        destination_path = os.path.join(output_dir, f"output_{score_id}.xml")
        logger.info(f"About to extract and copy MusicXML file:")
        logger.info(f"  Source MXL: {output_mxl_path}")
        logger.info(f"  Source exists: {os.path.exists(output_mxl_path)}")
        logger.info(f"  Output directory: {output_dir}")
        logger.info(f"  Output directory exists: {os.path.exists(output_dir)}")
        logger.info(f"  Output directory writable: {os.access(output_dir, os.W_OK)}")
        logger.info(f"  Destination XML: {destination_path}")

        with zipfile.ZipFile(output_mxl_path, "r") as mxl_zip:
            file_list = mxl_zip.namelist()
            xml_files = [f for f in file_list if f.endswith(".xml") and "/" not in f]
            if not xml_files:
                xml_files = [f for f in file_list if f.endswith(".xml")]
            if not xml_files:
                raise Exception("No XML file found in MXL archive")
            xml_filename = xml_files[0]
            logger.info(f"Extracting XML file: {xml_filename}")
            with mxl_zip.open(xml_filename) as xml_file:
                xml_content = xml_file.read()
                with open(destination_path, "wb") as output_file:
                    output_file.write(xml_content)
        logger.info(f"Successfully extracted and saved XML file to: {destination_path}")

        if os.path.exists(destination_path):
            file_size = os.path.getsize(destination_path)
            logger.info(f"XML file created successfully. Size: {file_size} bytes")
        else:
            logger.error("XML file was not created despite successful extraction")
    except Exception as e:
        logger.error(
            f"Failed to extract and copy XML file to output directory: {str(e)}"
        )
        logger.error(f"Exception type: {type(e).__name__}")
        logger.error(f"Traceback: {traceback.format_exc()}")

    return output_mxl_path, xml_output_path
