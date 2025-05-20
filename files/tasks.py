import os
import logging
from celery import shared_task
from django.conf import settings
from .models import PDFFile, PDFFileStorage
import docker
from music21 import converter, tempo, chord

logger = logging.getLogger(__name__)

@shared_task
def process_score(score_id):
    try:
        # Step 1: Get the PDFFile object
        score = PDFFile.objects.get(id=score_id)
        pdf_path = score.pdf_file.name
        logger.info(f"Processing score {score_id}: {pdf_path}")

        # Use the custom storage class
        storage = PDFFileStorage()
        logger.info(f"Using storage: {storage.__class__.__name__}")
        logger.info(f"Storage location: {storage.location}")

        # Check if file exists in R2
        full_path = f"{storage.location}/{pdf_path}"
        if not storage.exists(pdf_path):
            logger.error(f"File not found in R2 at {full_path}")
            score.results = f"File not found in R2 at {full_path}"
            score.processed = True
            score.save()
            return

        logger.info(f"File found in R2 at {pdf_path}")

        # Step 2: Download PDF to /app/processing/input directory
        input_dir = "/app/processing/input"  # Adjusted to match WORKDIR /app
        os.makedirs(input_dir, exist_ok=True)
        local_pdf_path = f"{input_dir}/score_{score_id}.pdf"
        try:
            with storage.open(pdf_path, 'rb') as pdf_file:
                with open(local_pdf_path, 'wb') as local_file:
                    local_file.write(pdf_file.read())
            logger.info(f"Downloaded PDF to {local_pdf_path}")
        except Exception as e:
            logger.error(f"Failed to download PDF from R2: {str(e)}")
            score.results = f"Failed to download PDF: {str(e)}"
            score.processed = True
            score.save()
            return

        # Debug: Verify the file exists in the input directory
        if not os.path.exists(local_pdf_path):
            logger.error(f"Downloaded PDF not found at {local_pdf_path}")
            logger.info(f"Input directory contents: {os.listdir(input_dir)}")
            score.results = f"Downloaded PDF not found at {local_pdf_path}"
            score.processed = True
            score.save()
            return
        logger.info(f"Confirmed PDF exists at {local_pdf_path}")
        logger.info(f"Input directory contents: {os.listdir(input_dir)}")

        # Step 3: Run Audiveris in a Docker container
        output_dir = "/app/processing/output"  # Adjusted to match WORKDIR /app
        os.makedirs(output_dir, exist_ok=True)
        musicxml_path = f"{output_dir}/score_{score_id}.mxl"
        try:
            client = docker.from_env()
            volumes = {
                input_dir: {'bind': '/input', 'mode': 'rw'},
                output_dir: {'bind': '/output', 'mode': 'rw'},
            }
            command = f"/input/score_{score_id}.pdf"
            logger.info(f"Running Audiveris with command: {command}, volumes: {volumes}")
            container = client.containers.run(
                image="gitahievans/audiveris:latest",
                name=f"audiveris_{score_id}",
                command=command,
                volumes=volumes,
                remove=True,
                stdout=True,
                stderr=True
            )
            logger.info(f"Audiveris output: {container.decode('utf-8')}")
            log_file = f"{output_dir}/audiveris.log"
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    logger.info(f"Audiveris log: {f.read()}")
            else:
                logger.warning(f"Audiveris log file not found at {log_file}")
        except Exception as e:
            logger.error(f"Audiveris failed: {str(e)}")
            score.results = f"Audiveris failed: {str(e)}"
            score.processed = True
            score.save()
            return

        # Step 4: Analyze MusicXML with music21
        if not os.path.exists(musicxml_path):
            logger.error(f"MusicXML file not found at {musicxml_path}")
            output_files = os.listdir(output_dir) if os.path.exists(output_dir) else []
            logger.info(f"Output directory contents: {output_files}")
            score.results = f"MusicXML generation failed. Output files: {output_files}"
            score.processed = True
            score.save()
            return

        try:
            score_stream = converter.parse(musicxml_path)
            analysis = {}
            key_analysis = score_stream.analyze('key')
            analysis['key'] = str(key_analysis)
            tempo_marks = score_stream.flatten().getElementsByClass(tempo.MetronomeMark)
            analysis['tempo'] = tempo_marks[0].number if tempo_marks else None
            chords = []
            for c in score_stream.flatten().getElementsByClass(chord.Chord):
                chords.append(c.pitchedCommonName)
            analysis['chords'] = chords[:10]
            logger.info(f"music21 analysis: {analysis}")
            score.results = str(analysis)
            score.processed = True
            score.save()
            logger.info(f"Saved analysis for score {score_id}")
        except Exception as e:
            logger.error(f"music21 analysis failed: {str(e)}")
            score.results = f"music21 analysis failed: {str(e)}"
            score.processed = True
            score.save()
            return

        # Clean up temporary files
        try:
            os.remove(local_pdf_path)
            if os.path.exists(musicxml_path):
                os.remove(musicxml_path)
            for file in os.listdir(output_dir):
                os.remove(os.path.join(output_dir, file))
        except Exception as e:
            logger.warning(f"Failed to clean up files: {str(e)}")

    except Exception as e:
        logger.error(f"Error processing score {score_id}: {str(e)}")
        try:
            score = PDFFile.objects.get(id=score_id)
            score.results = f"Error: {str(e)}"
            score.processed = True
            score.save()
        except Exception as save_e:
            logger.error(f"Failed to save error state for score {score_id}: {save_e}")