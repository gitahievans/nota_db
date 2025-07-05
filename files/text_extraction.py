# text_extraction.py
import cv2
import pytesseract
import PyPDF2
import pdfplumber
import logging
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)


class TextExtractor:
    def __init__(self):
        # Configure Tesseract if needed
        # pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'  # Adjust path
        pass

    def extract_from_file(self, file_path, file_ext):
        """Main method to extract text from file"""
        if file_ext.lower() == "pdf":
            return self._extract_from_pdf(file_path)
        elif file_ext.lower() in ["jpg", "jpeg", "png", "tiff", "tif"]:
            return self._extract_from_image(file_path)
        else:
            return {"error": f"Unsupported file format: {file_ext}"}

    def _extract_from_pdf(self, pdf_path):
        """Extract text from PDF (text-based PDFs only for now)"""
        try:
            # Try direct text extraction first
            text_content = self._extract_text_directly_from_pdf(pdf_path)

            if len(text_content.strip()) > 50:  # Likely text-based PDF
                logger.info("PDF appears to be text-based, using direct extraction")
                return self._structure_pdf_text(text_content)
            else:
                logger.info("PDF appears to be image-based, skipping for now")
                return {"message": "Image-based PDF detected. Not implemented yet."}

        except Exception as e:
            logger.error(f"PDF text extraction failed: {str(e)}")
            return {"error": f"PDF text extraction failed: {str(e)}"}

    def _extract_text_directly_from_pdf(self, pdf_path):
        """Extract text directly from PDF using pdfplumber"""
        text_content = ""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text_content += page.extract_text() or ""
                    text_content += "\n"
        except Exception as e:
            logger.warning(f"pdfplumber failed, trying PyPDF2: {str(e)}")
            # Fallback to PyPDF2
            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text_content += page.extract_text()
                    text_content += "\n"

        return text_content

    def _extract_from_image(self, image_path):
        """Extract text from image using OCR"""
        try:
            # Load image
            img = cv2.imread(str(image_path))
            if img is None:
                return {"error": "Could not load image"}

            # Apply text-optimized preprocessing
            processed_img = self._preprocess_for_text(img)

            # Extract text using OCR
            text = pytesseract.image_to_string(processed_img)

            # Structure the extracted text
            return self._structure_image_text(text, image_path)

        except Exception as e:
            logger.error(f"Image text extraction failed: {str(e)}")
            return {"error": f"Image text extraction failed: {str(e)}"}

    def _preprocess_for_text(self, img):
        """Preprocess image specifically for text extraction"""
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Apply slight blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)

        # Enhance contrast for text
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(blurred)

        # Apply threshold to get clean text
        _, thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Remove staff lines and musical notation
        thresh = self._remove_staff_lines(thresh)

        return thresh

    def _remove_staff_lines(self, img):
        """Remove horizontal staff lines that interfere with text recognition"""
        # Create horizontal kernel to detect staff lines
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))

        # Detect horizontal lines
        horizontal_lines = cv2.morphologyEx(img, cv2.MORPH_OPEN, horizontal_kernel)

        # Remove detected lines from original image
        img_without_lines = cv2.subtract(img, horizontal_lines)

        # Clean up small artifacts
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        cleaned = cv2.morphologyEx(img_without_lines, cv2.MORPH_CLOSE, kernel)

        return cleaned

    def _structure_pdf_text(self, text_content):
        """Structure text extracted from PDF"""
        lines = [line.strip() for line in text_content.split("\n") if line.strip()]

        result = {
            "title": None,
            "composer": None,
            "lyrics": [],
            "performance_instructions": [],
            "other_text": [],
        }

        # Simple heuristics for PDF text
        if lines:
            # First non-empty line is likely the title
            result["title"] = lines[0] if lines else None

            # Look for composer (often second line or contains "by")
            for line in lines[1:5]:  # Check first few lines
                if any(
                    keyword in line.lower() for keyword in ["by ", "composed", "music"]
                ):
                    result["composer"] = line
                    break

            # Rest goes to other_text for now
            result["other_text"] = lines[1:] if len(lines) > 1 else []

        return result

    def _structure_image_text(self, text, image_path):
        """Structure text extracted from image"""
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        # Filter out gibberish and musical notation
        filtered_lines = []
        for line in lines:
            if self._is_valid_text_line(line):
                filtered_lines.append(line)

        # Apply additional post-processing
        filtered_lines = self._post_process_text_lines(filtered_lines)

        result = {
            "title": None,
            "composer": None,
            "lyrics": [],
            "performance_instructions": [],
            "other_text": [],
        }

        # Basic text classification
        musical_terms = [
            "allegro",
            "adagio",
            "andante",
            "moderato",
            "largo",
            "presto",
            "forte",
            "piano",
            "mezzo",
            "crescendo",
            "diminuendo",
            "dolce",
            "pp",
            "p",
            "mp",
            "mf",
            "f",
            "ff",
            "fff",
            "ritardando",
            "accelerando",
            "legato",
            "staccato",
            "marcato",
        ]

        for line in filtered_lines:
            line_lower = line.lower()

            # Check if it's a performance instruction
            if any(term in line_lower for term in musical_terms):
                result["performance_instructions"].append(line)
            # Check if it looks like a title (first line, or contains common title patterns)
            elif not result["title"] and (
                filtered_lines.index(line) == 0 or len(line) > 10
            ):
                result["title"] = line
            # Check if it looks like composer info
            elif (
                any(
                    keyword in line_lower
                    for keyword in ["by ", "composed", "music", "composer"]
                )
                or
                # Check for names that look like composers (contain periods, common name patterns)
                (
                    len(line.split()) <= 3
                    and any(char.isupper() for char in line)
                    and "." in line
                )
            ):
                result["composer"] = line
            # Check if it looks like lyrics (contains common lyrical patterns)
            elif self._looks_like_lyrics(line):
                result["lyrics"].append(line)
            else:
                result["other_text"].append(line)

        return result

    def _is_valid_text_line(self, line):
        """Check if a line contains valid text and not musical notation gibberish"""
        # Remove whitespace for analysis
        clean_line = line.strip()

        # Skip empty lines
        if not clean_line:
            return False

        # Skip lines that are too short (likely artifacts)
        if len(clean_line) < 3:
            return False

        # Skip lines with Unicode musical symbols (common range for musical notation)
        if any(ord(char) > 0xF000 for char in clean_line):
            return False

        # Skip lines with too many special characters (musical notation)
        special_char_count = sum(
            1 for char in clean_line if not char.isalnum() and char not in " -.,!?"
        )
        if (
            special_char_count > len(clean_line) * 0.4
        ):  # More than 40% special characters
            return False

        # Skip lines that are mostly symbols or numbers
        alpha_count = sum(1 for char in clean_line if char.isalpha())
        if alpha_count < len(clean_line) * 0.4:  # Less than 40% alphabetic characters
            return False

        # Skip lines with repetitive patterns (likely staff notation)
        if len(set(clean_line.replace(" ", ""))) < 3:  # Too few unique characters
            return False

        # Skip lines that are mostly whitespace or single characters repeated
        words = clean_line.split()
        if len(words) < 2 and len(clean_line) < 8:  # Very short single words
            return False

        # Skip lines with excessive spacing patterns (musical notation artifacts)
        if clean_line.count(" ") > len(clean_line) * 0.6:  # More than 60% spaces
            return False

        # Skip lines that look like musical notation patterns
        notation_patterns = [
            r"^\s*[A-G]\s*[A-G]\s*[A-G]\s*$",  # Note sequences like "E e Na"
            r"^\s*[\d\s\-\.]+$",  # Only numbers, spaces, dashes, dots
            r"^\s*[f\s\-]+$",  # Repeated f's (forte markings)
            r"^\s*[\#\b\s\-]+$",  # Sharp/flat symbols
        ]

        import re

        for pattern in notation_patterns:
            if re.match(pattern, clean_line):
                return False

        return True

    def _post_process_text_lines(self, lines):
        """Additional filtering after initial text extraction"""
        filtered_lines = []

        for line in lines:
            # Skip lines that are mostly single characters scattered with spaces
            if len(line.replace(" ", "")) < 4:
                continue

            # Skip lines with suspicious patterns
            suspicious_patterns = [
                "Na fsi",  # Fragmented words
                "Ee nafsi",  # Partial words
                "ya ngu",  # Fragmented phrases
            ]

            if any(pattern in line for pattern in suspicious_patterns):
                continue

            # Skip lines that are mostly punctuation or special characters
            clean_content = "".join(char for char in line if char.isalnum())
            if len(clean_content) < 4:
                continue

            filtered_lines.append(line)

        return filtered_lines

    def _looks_like_lyrics(self, line):
        """Check if a line looks like song lyrics"""
        line_lower = line.lower()

        # Common lyrical indicators
        lyrical_patterns = [
            "na ",
            "ya ",
            "wa ",
            "ku ",
            "ni ",
            "si ",  # Swahili particles
            "the ",
            "and ",
            "of ",
            "in ",
            "to ",
            "a ",  # English articles/prepositions
            "bwana",
            "mungu",
            "yesu",
            "kristo",  # Religious terms in Swahili
            "lord",
            "god",
            "jesus",
            "christ",  # Religious terms in English
        ]

        # Check for verse/chorus indicators
        if any(
            indicator in line_lower
            for indicator in ["verse", "chorus", "refrain", "bridge"]
        ):
            return True

        # Check for common lyrical patterns
        if any(pattern in line_lower for pattern in lyrical_patterns):
            return True

        # Check for repeated words (common in lyrics)
        words = line_lower.split()
        if len(words) > 1 and len(set(words)) < len(words):
            return True

        return False
