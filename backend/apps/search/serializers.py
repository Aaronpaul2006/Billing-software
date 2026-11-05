from rest_framework import serializers

from apps.catalog.models import CatalogItem
from apps.documents.models import Document
from apps.parties.models import Party
from apps.projects.models import Project


class SearchParamsSerializer(serializers.Serializer[dict[str, str]]):
    q = serializers.CharField(min_length=2, max_length=100)


class SearchDocumentSerializer(serializers.ModelSerializer[Document]):
    party_name = serializers.SerializerMethodField(
        help_text="As frozen at issue; the party's current name on drafts."
    )

    class Meta:
        model = Document
        fields: tuple[str, ...] = (
            "id",
            "doc_type",
            "status",
            "doc_number",
            "doc_date",
            "party_name",
            "grand_total",
        )
        read_only_fields = fields

    def get_party_name(self, obj: Document) -> str:
        name = (obj.party_snapshot or {}).get("display_name")
        return str(name) if name else obj.party.display_name


class SearchPartySerializer(serializers.ModelSerializer[Party]):
    class Meta:
        model = Party
        fields: tuple[str, ...] = (
            "id",
            "display_name",
            "gstin",
            "is_customer",
            "is_vendor",
            "is_active",
        )
        read_only_fields = fields


class SearchProjectSerializer(serializers.ModelSerializer[Project]):
    client_name = serializers.CharField(source="client_party.display_name", read_only=True)

    class Meta:
        model = Project
        fields: tuple[str, ...] = ("id", "code", "name", "client_name", "status")
        read_only_fields = fields


class SearchCatalogItemSerializer(serializers.ModelSerializer[CatalogItem]):
    class Meta:
        model = CatalogItem
        fields: tuple[str, ...] = ("id", "name", "unit", "sac_hsn", "default_rate")
        read_only_fields = fields


class SearchResultSerializer(serializers.Serializer[dict[str, object]]):
    documents = SearchDocumentSerializer(many=True)
    parties = SearchPartySerializer(many=True)
    projects = SearchProjectSerializer(many=True)
    catalog_items = SearchCatalogItemSerializer(many=True)
