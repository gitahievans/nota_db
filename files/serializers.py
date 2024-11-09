from rest_framework import serializers
from .models import PDFFile, Category


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


class PDFFileSerializer(serializers.ModelSerializer):
    categories = CategorySerializer(many=True, required=False)

    class Meta:
        model = PDFFile
        fields = "__all__"

    def validate_file(self, value):
        if value.content_type != "application/pdf":
            raise serializers.ValidationError("Only PDF files are allowed.")
        return value

    def create(self, validated_data):
        categories_data = validated_data.pop("categories", [])
        pdf_file = PDFFile.objects.create(**validated_data)

        for category_data in categories_data:
            category_data = category_data.get("name")
            category = Category.objects.get_or_create(name=category_data)
            pdf_file.categories.add(category)

        return pdf_file

    def update(self, instance, validated_data):
        categories_data = validated_data.pop("categories", None)

        # Update PDFFile fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Update categories if provided
        if categories_data is not None:
            # Clear existing categories
            instance.categories.clear()
            for category_data in categories_data:
                category_name = category_data.get("name")
                category, _ = Category.objects.get_or_create(name=category_name)
                instance.categories.add(category)

        return instance

    def to_internal_value(self, data):
        categories_data = data.get("categories", [])
        if categories_data:
            if isinstance(categories_data[0], str):
                data["categories"] = [{"name": name} for name in categories_data]

        return super().to_internal_value(data)
