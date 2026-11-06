"""Importing masters from Tally (Part B): the reader, then the API.

ERP9 is a Tally.ERP 9 style export (GST fields on the ledger, a client under
a sub-group of Sundry Debtors, Tally's &#4; character references); PRIME3 a
TallyPrime 3 style one (LEDGSTREGDETAILS.LIST and LEDMAILINGDETAILS.LIST,
HSNDETAILS.LIST), as Tally writes them.
"""

import uuid
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.catalog.models import CatalogItem
from apps.core.errors import Invalid
from apps.core.tenancy import tenant_context
from apps.parties import tally
from apps.parties.models import Party
from tests.factories import add_member, gstin, make_tenant, owner_member

SKYLINE = gstin("32", pan="AAACS4321K")
STEEL = gstin("33", pan="AAACK1234M")
COASTAL = gstin("29", pan="AAACC5678P")

ERP9 = f"""<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
 <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
 <BODY><IMPORTDATA>
  <REQUESTDESC><REPORTNAME>All Masters</REPORTNAME></REQUESTDESC>
  <REQUESTDATA>
   <TALLYMESSAGE xmlns:UDF="TallyUDF">
    <GROUP NAME="Sundry Debtors" RESERVEDNAME="Sundry Debtors">
     <PARENT>&#4; Current Assets</PARENT>
    </GROUP>
   </TALLYMESSAGE>
   <TALLYMESSAGE xmlns:UDF="TallyUDF">
    <GROUP NAME="Kochi Clients" RESERVEDNAME="">
     <PARENT>Sundry Debtors</PARENT>
    </GROUP>
   </TALLYMESSAGE>
   <TALLYMESSAGE xmlns:UDF="TallyUDF">
    <LEDGER NAME="Skyline Developers" RESERVEDNAME="">
     <ADDRESS.LIST TYPE="String">
      <ADDRESS>12 MG Road</ADDRESS>
      <ADDRESS>Ernakulam South</ADDRESS>
      <ADDRESS>Kochi</ADDRESS>
     </ADDRESS.LIST>
     <MAILINGNAME.LIST TYPE="String">
      <MAILINGNAME>Skyline Developers Pvt Ltd</MAILINGNAME>
     </MAILINGNAME.LIST>
     <PARENT>Kochi Clients</PARENT>
     <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
     <PARTYGSTIN>{SKYLINE}</PARTYGSTIN>
     <LEDSTATENAME>Kerala</LEDSTATENAME>
     <COUNTRYNAME>India</COUNTRYNAME>
     <INCOMETAXNUMBER>AAACS4321K</INCOMETAXNUMBER>
     <EMAIL>accounts@skyline.example</EMAIL>
     <LEDGERMOBILE>98470 12345</LEDGERMOBILE>
     <PINCODE>682016</PINCODE>
     <BILLCREDITPERIOD>30 Days</BILLCREDITPERIOD>
     <LANGUAGENAME.LIST>
      <NAME.LIST TYPE="String"><NAME>Skyline Developers</NAME></NAME.LIST>
     </LANGUAGENAME.LIST>
    </LEDGER>
   </TALLYMESSAGE>
   <TALLYMESSAGE xmlns:UDF="TallyUDF">
    <LEDGER NAME="Anna Kurian" RESERVEDNAME="">
     <PARENT>Sundry Debtors</PARENT>
     <GSTREGISTRATIONTYPE>Consumer</GSTREGISTRATIONTYPE>
     <LEDSTATENAME>Kerala</LEDSTATENAME>
    </LEDGER>
   </TALLYMESSAGE>
   <TALLYMESSAGE xmlns:UDF="TallyUDF">
    <LEDGER NAME="Wrong GSTIN Builders" RESERVEDNAME="">
     <PARENT>Sundry Debtors</PARENT>
     <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
     <PARTYGSTIN>32AAAAA0000A1Z0</PARTYGSTIN>
    </LEDGER>
   </TALLYMESSAGE>
   <TALLYMESSAGE xmlns:UDF="TallyUDF">
    <LEDGER NAME="HDFC Bank" RESERVEDNAME="">
     <PARENT>Bank Accounts</PARENT>
    </LEDGER>
   </TALLYMESSAGE>
   <TALLYMESSAGE xmlns:UDF="TallyUDF">
    <LEDGER NAME="Output CGST" RESERVEDNAME="">
     <PARENT>Duties &amp; Taxes</PARENT>
    </LEDGER>
   </TALLYMESSAGE>
   <TALLYMESSAGE xmlns:UDF="TallyUDF">
    <STOCKITEM NAME="OPC 53 Cement" RESERVEDNAME="">
     <PARENT/>
     <BASEUNITS>Bag</BASEUNITS>
     <GSTDETAILS.LIST>
      <APPLICABLEFROM>20170701</APPLICABLEFROM>
      <HSNCODE>2523</HSNCODE>
      <STATEWISEDETAILS.LIST>
       <STATENAME>&#4; Any</STATENAME>
       <RATEDETAILS.LIST>
        <GSTRATEDUTYHEAD>Integrated Tax</GSTRATEDUTYHEAD><GSTRATE> 28</GSTRATE>
       </RATEDETAILS.LIST>
      </STATEWISEDETAILS.LIST>
     </GSTDETAILS.LIST>
     <GSTDETAILS.LIST>
      <APPLICABLEFROM>20250922</APPLICABLEFROM>
      <HSNCODE>2523</HSNCODE>
      <STATEWISEDETAILS.LIST>
       <STATENAME>&#4; Any</STATENAME>
       <RATEDETAILS.LIST>
        <GSTRATEDUTYHEAD>Central Tax</GSTRATEDUTYHEAD><GSTRATE> 9</GSTRATE>
       </RATEDETAILS.LIST>
       <RATEDETAILS.LIST>
        <GSTRATEDUTYHEAD>Integrated Tax</GSTRATEDUTYHEAD><GSTRATE> 18</GSTRATE>
       </RATEDETAILS.LIST>
      </STATEWISEDETAILS.LIST>
     </GSTDETAILS.LIST>
     <STANDARDPRICELIST.LIST>
      <DATE>20240401</DATE><RATE>360.00/Bag</RATE>
     </STANDARDPRICELIST.LIST>
     <STANDARDPRICELIST.LIST>
      <DATE>20260401</DATE><RATE>380.00/Bag</RATE>
     </STANDARDPRICELIST.LIST>
    </STOCKITEM>
   </TALLYMESSAGE>
   <TALLYMESSAGE xmlns:UDF="TallyUDF">
    <STOCKITEM NAME="Odd HSN item" RESERVEDNAME="">
     <BASEUNITS>Nos</BASEUNITS>
     <GSTDETAILS.LIST><HSNCODE>AB12</HSNCODE></GSTDETAILS.LIST>
    </STOCKITEM>
   </TALLYMESSAGE>
  </REQUESTDATA>
 </IMPORTDATA></BODY>
</ENVELOPE>
"""

PRIME3 = f"""<ENVELOPE>
 <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
 <BODY><IMPORTDATA><REQUESTDATA>
  <TALLYMESSAGE xmlns:UDF="TallyUDF">
   <LEDGER NAME="Kerala Steel Traders" RESERVEDNAME="">
    <PARENT>Sundry Creditors</PARENT>
    <INCOMETAXNUMBER>AAACK1234M</INCOMETAXNUMBER>
    <LEDGERPHONE>0484 2345678</LEDGERPHONE>
    <BILLCREDITPERIOD>45 Days</BILLCREDITPERIOD>
    <LEDGSTREGDETAILS.LIST>
     <APPLICABLEFROM>20230401</APPLICABLEFROM>
     <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
     <STATE>Tamil Nadu</STATE>
     <GSTIN>{STEEL}</GSTIN>
    </LEDGSTREGDETAILS.LIST>
    <LEDMAILINGDETAILS.LIST>
     <ADDRESS.LIST TYPE="String">
      <ADDRESS>4 Industrial Estate</ADDRESS>
      <ADDRESS>Coimbatore</ADDRESS>
     </ADDRESS.LIST>
     <APPLICABLEFROM>20230401</APPLICABLEFROM>
     <PINCODE>641021</PINCODE>
     <MAILINGNAME>Kerala Steel Traders</MAILINGNAME>
     <STATE>Tamil Nadu</STATE>
     <COUNTRY>India</COUNTRY>
    </LEDMAILINGDETAILS.LIST>
   </LEDGER>
  </TALLYMESSAGE>
  <TALLYMESSAGE xmlns:UDF="TallyUDF">
   <LEDGER NAME="Coastal Homes" RESERVEDNAME="">
    <PARENT>Sundry Debtors</PARENT>
    <LEDGSTREGDETAILS.LIST>
     <APPLICABLEFROM>20240401</APPLICABLEFROM>
     <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
     <GSTIN>{COASTAL}</GSTIN>
    </LEDGSTREGDETAILS.LIST>
    <LEDMAILINGDETAILS.LIST>
     <ADDRESS.LIST TYPE="String">
      <ADDRESS>Whitefield</ADDRESS>
      <ADDRESS>Bengaluru</ADDRESS>
     </ADDRESS.LIST>
     <APPLICABLEFROM>20240401</APPLICABLEFROM>
     <PINCODE>56</PINCODE>
    </LEDMAILINGDETAILS.LIST>
   </LEDGER>
  </TALLYMESSAGE>
  <TALLYMESSAGE xmlns:UDF="TallyUDF">
   <STOCKITEM NAME="TMT steel bar 12 mm" RESERVEDNAME="">
    <BASEUNITS>kg</BASEUNITS>
    <HSNDETAILS.LIST><APPLICABLEFROM>20230401</APPLICABLEFROM><HSNCODE>7214</HSNCODE></HSNDETAILS.LIST>
    <GSTDETAILS.LIST>
     <APPLICABLEFROM>20230401</APPLICABLEFROM>
     <STATEWISEDETAILS.LIST>
      <RATEDETAILS.LIST>
       <GSTRATEDUTYHEAD>IGST</GSTRATEDUTYHEAD><GSTRATE>18</GSTRATE>
      </RATEDETAILS.LIST>
     </STATEWISEDETAILS.LIST>
    </GSTDETAILS.LIST>
   </STOCKITEM>
  </TALLYMESSAGE>
 </REQUESTDATA></IMPORTDATA></BODY>
</ENVELOPE>
"""


# --- the reader ------------------------------------------------------------


def test_reads_an_erp9_export() -> None:
    m = tally.read(ERP9.encode())
    assert [x.name for x in m.ledgers] == [
        "Skyline Developers",
        "Anna Kurian",
        "Wrong GSTIN Builders",
    ]
    assert m.other_ledgers == 2  # the bank and the tax ledger
    sky = m.ledgers[0]
    assert sky.kind == "CLIENT"  # Kochi Clients is under Sundry Debtors
    assert (sky.gstin, sky.gst_type, sky.state, sky.pan) == (
        SKYLINE,
        "Regular",
        "Kerala",
        "AAACS4321K",
    )
    assert sky.address == ["12 MG Road", "Ernakulam South", "Kochi"]
    assert (sky.pincode, sky.credit_days, sky.phone) == ("682016", "30", "98470 12345")
    assert sky.mailing_name == "Skyline Developers Pvt Ltd"
    cement = m.items[0]
    # the newest GST details and price win: cement went from 28 % to 18 % in 2025
    assert (cement.unit, cement.hsn, cement.gst_rate, cement.rate) == (
        "Bag",
        "2523",
        "18",
        "380.00",
    )


def test_reads_a_tallyprime_3_export() -> None:
    m = tally.read(PRIME3.encode())
    steel, coastal = m.ledgers
    assert steel.kind == "VENDOR"
    assert (steel.gstin, steel.state, steel.pincode) == (STEEL, "Tamil Nadu", "641021")
    assert steel.address == ["4 Industrial Estate", "Coimbatore"]
    assert coastal.kind == "CLIENT"
    tmt = m.items[0]
    assert (tmt.hsn, tmt.gst_rate, tmt.unit) == ("7214", "18", "kg")


def test_reads_utf16_and_refuses_what_is_not_tally_xml() -> None:
    utf16 = ERP9.replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16")
    assert len(tally.read(utf16).ledgers) == 3
    bomb = b'<!DOCTYPE x [<!ENTITY a "aaaa">]><ENVELOPE>&a;</ENVELOPE>'
    for data in (b"Name,GSTIN\nSkyline,\n", bomb):
        with pytest.raises(Invalid) as e:
            tally.read(data)
        assert e.value.code == "not_tally_xml"
    with pytest.raises(Invalid) as e:
        tally.read(b"<ENVELOPE><BODY/></ENVELOPE>")
    assert e.value.code == "no_masters"


# --- the API ---------------------------------------------------------------


class Books:
    def __init__(self, name: str = "Nair Constructions") -> None:
        self.t = make_tenant(name)
        self.owner = owner_member(self.t)

    def send(self, xml: str, member: Any = None, **body: Any) -> Any:
        m = member or self.owner
        return APIClient().post(
            "/api/v1/tally-imports",
            {"file": SimpleUploadedFile("Master.xml", xml.encode(), "text/xml"), **body},
            format="multipart",
            HTTP_AUTHORIZATION=f"Bearer {m.access_token}",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )


@pytest.fixture
def b() -> Books:
    return Books()


pytestmark = pytest.mark.django_db


def test_preview_then_import_and_again(b: Books) -> None:
    with tenant_context(b.t.tenant_id, b.t.user_id):
        Party.objects.create(
            display_name="anna kurian", gst_treatment="CONSUMER", created_by_id=b.t.user_id
        )
    r = b.send(ERP9, dry_run="true")
    assert r.status_code == 200, r.content
    p = r.json()
    assert p["clients"] == {"new": 1, "exists": 1, "problems": 1}
    assert p["items"] == {"new": 1, "exists": 0, "problems": 1}
    assert p["other_ledgers"] == 2
    assert p["added"] is None
    first = p["rows"][0]
    assert (first["status"], first["name"]) == ("PROBLEM", "Wrong GSTIN Builders")
    assert first["message"].startswith("gstin: ")
    assert [r["status"] for r in p["rows"]] == ["PROBLEM", "PROBLEM", "NEW", "NEW", "EXISTS"]
    with tenant_context(b.t.tenant_id, b.t.user_id):
        assert Party.objects.count() == 1  # a preview saves nothing

    r = b.send(ERP9)
    assert r.status_code == 201, r.content
    assert r.json()["added"] == {"CLIENT": 1, "VENDOR": 0, "ITEM": 1}
    with tenant_context(b.t.tenant_id, b.t.user_id):
        sky = Party.objects.get(display_name="Skyline Developers")
        assert (sky.gstin, sky.state_code, sky.gst_treatment) == (SKYLINE, "32", "REGISTERED")
        assert (sky.legal_name, sky.pan, sky.phone) == (
            "Skyline Developers Pvt Ltd",
            "AAACS4321K",
            "9847012345",
        )
        assert sky.payment_terms_days == 30
        assert (sky.is_customer, sky.is_vendor) == (True, False)
        assert sky.billing_address == {
            "line1": "12 MG Road",
            "line2": "Ernakulam South",
            "city": "Kochi",
            "pincode": "682016",
            "state_code": "32",
            "country": "IN",
        }
        cement = CatalogItem.objects.get(name="OPC 53 Cement")
        assert (cement.unit, cement.sac_hsn, str(cement.gst_rate), str(cement.default_rate)) == (
            "Bag",
            "2523",
            "18.00",
            "380.00",
        )

    again = b.send(ERP9, dry_run="true").json()  # the same file again: nothing new
    assert again["clients"]["new"] == again["items"]["new"] == 0
    r = b.send(ERP9)
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "nothing_new"


def test_only_the_kinds_chosen_and_an_address_left_out(b: Books) -> None:
    r = b.send(PRIME3, kinds=["VENDOR"])
    assert r.status_code == 201, r.content
    assert r.json()["added"] == {"CLIENT": 0, "VENDOR": 1, "ITEM": 0}
    with tenant_context(b.t.tenant_id, b.t.user_id):
        steel = Party.objects.get(display_name="Kerala Steel Traders")
        assert (steel.is_customer, steel.is_vendor) == (False, True)
        assert (steel.state_code, steel.payment_terms_days) == ("33", 45)
        assert steel.billing_address["city"] == "Coimbatore"
        assert not Party.objects.filter(display_name="Coastal Homes").exists()
    p = b.send(PRIME3, dry_run="true").json()
    coastal = next(r for r in p["rows"] if r["name"] == "Coastal Homes")
    assert coastal["status"] == "NEW"  # added without the address: its PIN code is wrong
    assert coastal["message"].startswith("Address left out: pincode")
    r = b.send(PRIME3, kinds=["CLIENT", "ITEM"])
    assert r.json()["added"] == {"CLIENT": 1, "VENDOR": 0, "ITEM": 1}
    with tenant_context(b.t.tenant_id, b.t.user_id):
        assert Party.objects.get(display_name="Coastal Homes").billing_address is None


def test_who_may_import(b: Books) -> None:
    accountant, engineer = add_member(b.t, "ACCOUNTANT"), add_member(b.t, "SITE_ENGINEER")
    assert b.send(ERP9, engineer, dry_run="true").status_code == 403
    assert b.send(ERP9, accountant, dry_run="true").status_code == 200
    r = b.send("not xml", dry_run="true")
    assert (r.status_code, r.json()["errors"][0]["code"]) == (422, "not_tally_xml")


def test_another_business_is_not_affected(b: Books) -> None:
    other = Books("Other Builders")
    assert other.send(ERP9).status_code == 201
    p = b.send(ERP9, dry_run="true").json()  # names in another business do not count
    assert p["clients"]["new"] == 2
    with tenant_context(b.t.tenant_id, b.t.user_id):
        assert Party.objects.count() == 0
