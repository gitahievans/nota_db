from rest_framework import serializers
from .models import PDFFile, Category
import json


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


import json
from rest_framework import serializers
from .models import PDFFile, Category
from .serializers import CategorySerializer


class FileSerializer(serializers.ModelSerializer):
    categories = CategorySerializer(many=True, required=False)
    results = serializers.SerializerMethodField()

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
        ]

    def get_results(self, obj):
        if obj.results:
            try:
                # If results is already a dict, return it; if a string, parse it
                if isinstance(obj.results, dict):
                    return obj.results
                return json.loads(obj.results)
            except json.JSONDecodeError as e:
                return {"error": f"Invalid JSON: {str(e)}"}
        return None

    def validate_file(self, value):
        allowed_content_types = [
            "application/pdf",
            "image/jpeg",
            "image/png",
            "image/tiff",
            "image/webp",
        ]
        if value.content_type not in allowed_content_types:
            raise serializers.ValidationError(
                f"Only PDF, JPG, PNG, and TIFF files are allowed. Got {value.content_type}."
            )
        # Optional: Add file size validation
        max_size = 10 * 1024 * 1024  # 10MB
        if value.size > max_size:
            raise serializers.ValidationError("File size exceeds 10MB limit.")
        return value

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

    def to_internal_value(self, data):
        data = data.copy()
        categories_data = data.get("categories")
        if categories_data and isinstance(categories_data[0], str):
            data["categories"] = [{"name": name} for name in categories_data]
        return super().to_internal_value(data)
