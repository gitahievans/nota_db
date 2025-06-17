from rest_framework import serializers
from .models import PDFFile, Category
import json


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


class PDFFileSerializer(serializers.ModelSerializer):
    categories = CategorySerializer(many=True, required=False)
    results = serializers.SerializerMethodField()

    class Meta:
        model = PDFFile
        fields = [
            "id",
            "title",
            "lyrics",
            "pdf_file",
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

    def validate_pdf_file(self, value):
        if value.content_type != "application/pdf":
            raise serializers.ValidationError("Only PDF files are allowed.")
        return value

    def create(self, validated_data):
        categories_data = validated_data.pop("categories", [])
        try:
            pdf_file = PDFFile.objects.create(**validated_data)
            for category_data in categories_data:
                if isinstance(category_data, dict):
                    category_name = category_data.get("name")
                else:
                    category_name = category_data
                category_obj, created = Category.objects.get_or_create(
                    name=category_name
                )
                pdf_file.categories.add(category_obj)
            return pdf_file
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
