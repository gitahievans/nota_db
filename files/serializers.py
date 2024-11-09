from rest_framework import serializers
from .models import PDFFile, Category


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


class PDFFileSerializer(serializers.ModelSerializer):
    categories = CategorySerializer(many=True)

    class Meta:
        model = PDFFile
        fields = "__all__"

    def validate_file(self, value):
        if value.content_type != "application/pdf":
            raise serializers.ValidationError("Only PDF files are allowed.")
        return value
