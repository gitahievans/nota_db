import json
from pathlib import Path

from rest_framework import serializers
from django.conf import settings

from .models import PDFFile, Category
from .outcomes import read_results, available

MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024

SUPPORTED_EXTENSIONS = {
    "pdf": PDFFile.SOURCE_TYPE_PDF,
    "jpg": PDFFile.SOURCE_TYPE_IMAGE,
    "jpeg": PDFFile.SOURCE_TYPE_IMAGE,
    "png": PDFFile.SOURCE_TYPE_IMAGE,
    "tiff": PDFFile.SOURCE_TYPE_IMAGE,
    "tif": PDFFile.SOURCE_TYPE_IMAGE,
    "webp": PDFFile.SOURCE_TYPE_IMAGE,
    "mp3": PDFFile.SOURCE_TYPE_AUDIO,
    "wav": PDFFile.SOURCE_TYPE_AUDIO,
    "m4a": PDFFile.SOURCE_TYPE_AUDIO,
}

SUPPORTED_MIME_TYPES = {
    "application/pdf": PDFFile.SOURCE_TYPE_PDF,
    "image/jpeg": PDFFile.SOURCE_TYPE_IMAGE,
    "image/png": PDFFile.SOURCE_TYPE_IMAGE,
    "image/tiff": PDFFile.SOURCE_TYPE_IMAGE,
    "image/tif": PDFFile.SOURCE_TYPE_IMAGE,
    "image/webp": PDFFile.SOURCE_TYPE_IMAGE,
    "audio/mpeg": PDFFile.SOURCE_TYPE_AUDIO,
    "audio/mp3": PDFFile.SOURCE_TYPE_AUDIO,
    "audio/wav": PDFFile.SOURCE_TYPE_AUDIO,
    "audio/x-wav": PDFFile.SOURCE_TYPE_AUDIO,
    "audio/wave": PDFFile.SOURCE_TYPE_AUDIO,
    "audio/vnd.wave": PDFFile.SOURCE_TYPE_AUDIO,
    "audio/mp4": PDFFile.SOURCE_TYPE_AUDIO,
    "audio/x-m4a": PDFFile.SOURCE_TYPE_AUDIO,
    "video/mp4": PDFFile.SOURCE_TYPE_AUDIO,
}

FALLBACK_MIME_TYPES = {"", None, "application/octet-stream"}


def get_extension(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def detect_source_type(filename: str) -> str | None:
    return SUPPORTED_EXTENSIONS.get(get_extension(filename))


def is_supported_upload(filename: str, content_type: str | None) -> bool:
    source_type = detect_source_type(filename)
    if not source_type:
        return False
    if content_type in FALLBACK_MIME_TYPES:
        return True
    return SUPPORTED_MIME_TYPES.get(content_type) == source_type


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


class FileSerializer(serializers.ModelSerializer):
    categories = CategorySerializer(many=True, required=False)
    results = serializers.SerializerMethodField()
    source_audio_url = serializers.SerializerMethodField()
    playback_midi_url = serializers.SerializerMethodField()
    raw_preview_midi_url = serializers.SerializerMethodField()

    class Meta:
        model = PDFFile
        fields = [
            "id",
            "title",
            "lyrics",
            "file",
            "composer",
            "year",
            "categories",
            "results",
            "processed",
            "musicxml_url",
            "midi_url",
            "source_type",
            "source_audio_url",
            "playback_midi_url",
            "raw_preview_midi_url",
        ]

    def get_results(self, obj):
        return read_results(obj.results) if obj.results else None

    def validate_file(self, value):
        if self.instance and self.instance.retention_kind == "analysis":
            raise serializers.ValidationError("Upload a new analysis session to process another input.")
        if not is_supported_upload(value.name, value.content_type):
            raise serializers.ValidationError(
                "Only PDF, JPEG, PNG, TIFF, WebP, MP3, WAV, and M4A files are allowed."
            )
        if value.size > MAX_UPLOAD_SIZE_BYTES:
            raise serializers.ValidationError("File size exceeds 10MB limit.")
        return value

    def get_source_audio_url(self, obj):
        if obj.source_type != PDFFile.SOURCE_TYPE_AUDIO:
            return None
        temp_dir = Path(settings.TEMP_STORAGE_DIR) / str(obj.id)
        for candidate in temp_dir.glob("input.*"):
            if candidate.suffix.lower() in {".mp3", ".wav", ".m4a"}:
                return f"/api/serve-source-audio/{obj.id}/"
        return None

    def get_playback_midi_url(self, obj):
        url = obj.midi_url
        return url if available(obj, "midi") else None

    def get_raw_preview_midi_url(self, obj):
        path = Path(settings.TEMP_STORAGE_DIR) / str(obj.id) / "preview.mid"
        if obj.source_type == PDFFile.SOURCE_TYPE_AUDIO and path.exists():
            return f"/api/serve-preview-midi/{obj.id}/"
        return None

    def create(self, validated_data):
        categories_data = validated_data.pop("categories", [])
        try:
            file_instance = PDFFile.objects.create(**validated_data)
            for category_data in categories_data:
                if isinstance(category_data, dict):
                    category_name = category_data.get("name")
                else:
                    category_name = category_data
                category_obj, created = Category.objects.get_or_create(
                    name=category_name
                )
                file_instance.categories.add(category_obj)
            return file_instance
        except Exception as e:
            print(f"Error in create: {str(e)}")
            raise

    def update(self, instance, validated_data):
        categories_data = validated_data.pop("categories", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if categories_data is not None:
            instance.categories.clear()
            for category_data in categories_data:
                category_name = category_data.get("name")
                category, created = Category.objects.get_or_create(name=category_name)
                instance.categories.add(category)
        return instance

    def to_representation(self, instance):
        from .lifecycle import lifetime
        data = super().to_representation(instance)
        data["lifetime"] = lifetime(instance)
        if not available(instance, "notation"):
            data["musicxml_url"] = None
        if not available(instance, "midi"):
            data["midi_url"] = None
        data["capabilities"] = {"notation": available(instance, "notation"), "default_playback": available(instance, "midi")}
        data["results_schema_version"] = read_results(instance.results).get("schema_version", 1)
        return data

    def to_internal_value(self, data):
        categories_data = data.get("categories")
        if categories_data and isinstance(categories_data[0], str):
            normalized_data = {
                key: data.getlist(key) if hasattr(data, "getlist") else value
                for key, value in data.items()
            }
            normalized_data["categories"] = [
                {"name": name} for name in categories_data
            ]
            return super().to_internal_value(normalized_data)
        return super().to_internal_value(data)
