#!/usr/bin/env python3
"""
Test script to validate image preprocessing for Audiveris.
Run this script to test your image preprocessing pipeline.
"""

import cv2
import numpy as np
from PIL import Image
import os
import sys


def analyze_image_for_audiveris(image_path):
    """Analyze an image to predict Audiveris compatibility."""
    print(f"Analyzing image: {image_path}")

    if not os.path.exists(image_path):
        print(f"Error: Image file not found: {image_path}")
        return False

    # Load image
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print("Error: Could not load image")
        return False

    height, width = img.shape
    print(f"Image dimensions: {width}x{height}")

    # Estimate DPI (assuming 8.5" width for typical sheet music)
    estimated_dpi = width / 8.5
    print(f"Estimated DPI: {estimated_dpi:.1f}")

    # Estimate interline spacing using horizontal projection
    # Sum pixels along horizontal lines
    horizontal_projection = np.sum(img < 128, axis=1)  # Count dark pixels per row

    # Find peaks (staff lines) in the projection
    from scipy.signal import find_peaks

    try:
        peaks, _ = find_peaks(
            horizontal_projection, height=np.max(horizontal_projection) * 0.1
        )
        if len(peaks) > 1:
            # Calculate average distance between peaks (staff lines)
            interline_distances = np.diff(peaks)
            avg_interline = np.mean(interline_distances)
            print(f"Estimated interline spacing: {avg_interline:.1f} pixels")

            # Audiveris recommendations
            if avg_interline < 15:
                print("⚠️  WARNING: Interline spacing too small - Audiveris may fail")
                print("   Recommendation: Increase image resolution")
                return False
            elif avg_interline >= 15 and avg_interline < 20:
                print("⚠️  CAUTION: Interline spacing borderline - results may vary")
                return True
            else:
                print("✅ Good interline spacing for Audiveris")
                return True
        else:
            print("⚠️  Could not detect staff lines reliably")
            return False
    except ImportError:
        print("Note: Install scipy for detailed interline analysis")
        # Fallback estimation
        estimated_interline = height / 50
        print(f"Rough interline estimate: {estimated_interline:.1f} pixels")
        return estimated_interline >= 15

    # Check image quality metrics
    # Calculate contrast (standard deviation)
    contrast = np.std(img)
    print(f"Image contrast (std dev): {contrast:.1f}")

    if contrast < 30:
        print("⚠️  Low contrast detected - may affect recognition")
    else:
        print("✅ Good contrast for recognition")

    # Check for noise level
    # Apply Laplacian to detect edges/noise
    laplacian_var = cv2.Laplacian(img, cv2.CV_64F).var()
    print(f"Edge/noise level: {laplacian_var:.1f}")

    return True


def preprocess_and_test(input_path, output_path=None):
    """Preprocess image and test the result."""
    if output_path is None:
        name, ext = os.path.splitext(input_path)
        output_path = f"{name}_processed{ext}"

    print("\n=== BEFORE PREPROCESSING ===")
    analyze_image_for_audiveris(input_path)

    # Apply the same preprocessing as in FileUploadView
    try:
        img = cv2.imread(input_path, cv2.IMREAD_COLOR)
        if img is None:
            pil_img = Image.open(input_path)
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        original_height, original_width = img.shape[:2]

        # Calculate scaling for 300 DPI target
        estimated_width_inches = 8.5
        current_dpi = original_width / estimated_width_inches
        target_dpi = 300

        if current_dpi < target_dpi:
            scale_factor = min(target_dpi / current_dpi, 3.0)
            new_width = int(original_width * scale_factor)
            new_height = int(original_height * scale_factor)
            img = cv2.resize(
                img, (new_width, new_height), interpolation=cv2.INTER_CUBIC
            )

        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

        # Apply preprocessing
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )

        # Clean up
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        # Save result
        cv2.imwrite(output_path, binary)
        print(f"\n=== AFTER PREPROCESSING ===")
        print(f"Processed image saved to: {output_path}")
        analyze_image_for_audiveris(output_path)

        return True
    except Exception as e:
        print(f"Preprocessing failed: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_image_preprocessing.py <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]
    preprocess_and_test(image_path)
