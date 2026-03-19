"""
Users Serializers
==================
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class UserTokenObtainPairSerializer(TokenObtainPairSerializer):
    """JWT con datos extra del usuario en el payload."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["is_staff"] = user.is_staff
        return token


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ("email", "username", "password", "phone")

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "phone",
            "default_address",
            "default_city",
            "default_province",
            "default_zip",
            "is_collector",
            "date_joined",
        )
        read_only_fields = ("id", "email", "date_joined", "is_collector")
