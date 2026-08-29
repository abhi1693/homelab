---
title: NetBox Hardware Lifecycle Data
---

# NetBox Hardware Lifecycle Data

- Service: NetBox and `netbox-lifecycle`
- Scope: physical Devices, Device Types, Module Types, warranties, and support
- Change path: NetBox MCP with an operator-visible change reference
- Normal mode: evidence collection followed by reviewed NetBox writes

## Meaning

Hardware lifecycle data answers two different questions that must not be mixed:

1. How long does the manufacturer sell, maintain, secure, or support a product
   model?
2. When was this particular unit acquired, warranted, deployed, or retired?

The `netbox-lifecycle` plugin owns product-level EOS/EOL dates on Device Types
and Module Types. Native NetBox Device fields own the unit's serial, asset tag,
and current operational status. Lifecycle support contracts own real warranty
or support agreements and their assignments to individual Devices.

## Impact

Missing or inferred lifecycle data can hide security-support deadlines, cause a
failed unit to be mistaken for an obsolete model, or make procurement decisions
from a product launch date instead of an actual warranty or EOL statement.
Never convert an estimate, retailer listing, controller first-seen timestamp, or
minimum production commitment into an EOS/EOL date.

## Source-of-truth boundaries

| Data | Authority | NetBox representation |
| --- | --- | --- |
| Product end of sale | Dated manufacturer notice | Hardware Lifecycle `end_of_sale` on the Device Type or Module Type |
| Product maintenance, security, or support end | Dated manufacturer support or compliance statement | The matching Hardware Lifecycle date field; do not substitute one date class for another |
| Minimum manufacturing availability | Manufacturer product or longevity statement | Hardware Lifecycle `notice` and `documentation`; it is not `end_of_sale` |
| Vintage, legacy, or discontinued status without a date | Current manufacturer lifecycle page | Hardware Lifecycle `notice`; leave date fields empty |
| Unit serial and internal asset label | Physical label, invoice, or other stable identity evidence | Native Device `serial` and optional `asset_tag` |
| Unit operational state | Confirmed physical and operational state | Native Device status such as `active`, `offline`, or `decommissioning` |
| Warranty or paid support | Contract, invoice, warranty certificate, or vendor confirmation | Lifecycle Vendor, Support Contract, and Support Contract Assignment |
| Distributor, reseller, or support contact | Confirmed commercial relationship | NetBox Contact, Contact Role, and Contact Assignment |
| Purchase date, purchase reference, or planned retirement | Invoice, order record, or operator decision | Instance-level procurement fields after the schema is separately reviewed; do not overload product lifecycle dates |

## Current baseline

As reviewed on 2026-08-28:

- NetBox has 31 active Devices using 19 Device Types.
- 23 Devices have a non-empty serial. Eight chassis, passive, storage, cooling,
  controller, or PDU records still need physical-label review; blank is safer
  than a guessed value.
- Asset tags are empty on all Devices. Asset tags are optional internal labels
  and must not be generated merely to duplicate a manufacturer serial.
- Hardware Lifecycle record 1 is assigned to Raspberry Pi 5. Its notice retains
  conflicting official minimum manufacturing commitments: January 2036 on the
  current product page and January 2038 in the later longevity statement. Every
  EOS/EOL date remains empty because neither is an end-of-sale announcement.
- Hardware Lifecycle record 2 is assigned to UniFi Dream Machine Pro. It records
  `end_of_security=2027-12-31` from Ubiquiti's published security statement;
  end of sale and general-support dates remain empty.
- No lifecycle Vendor, Support SKU, Support Contract, Contract Assignment,
  License, or License Assignment has been confirmed yet.

## Diagnosis

1. Discover plugin object types and require all of these before writing:
   `netbox_lifecycle.hardwarelifecycle`, `vendor`, `supportsku`,
   `supportcontract`, and `supportcontractassignment`.
2. Read Hardware Lifecycle objects with pagination capped at 500. Require at
   most one record per assigned Device Type or Module Type.
3. Read all in-use Device Types and their Device counts. A missing lifecycle
   record is a documentation gap, not evidence that the model is supported
   forever or already obsolete.
4. Read Devices with `id`, `name`, `device_type`, `status`, `serial`,
   `asset_tag`, `site`, `location`, and `rack`. Do not treat passive components
   without manufacturer serials as identity failures.
5. Read contracts and assignments independently. A product lifecycle record
   does not prove that a particular unit is still under warranty.
6. For every proposed date, retain the direct manufacturer or commercial
   evidence URL/reference and classify it as sale, maintenance, security,
   support, warranty, or minimum availability before choosing a NetBox field.

## Mitigation

Apply only confirmed facts through the NetBox MCP server:

1. Re-read the target Device Type or Device and any existing lifecycle or
   contract object immediately before writing.
2. For model-level data, create or update the single Hardware Lifecycle record
   assigned to `dcim.devicetype` or `dcim.moduletype`.
3. Put only a date that the source explicitly classifies into the matching
   field. Store qualified or status-only statements in `notice` and retain the
   direct source in `documentation`.
4. For a real warranty or paid support agreement, create the actual Vendor and
   contract reference, then assign the contract to the exact Device. Do not
   invent contract identifiers to satisfy a required field.
5. Change a Device to `decommissioning` only after the unit is intentionally
   being removed. Preserve its record and add a journal entry or comments with
   the decision evidence; do not delete it as routine cleanup.
6. Use one bounded change reference for the reviewed batch and retain the
   source and review date in comments.

The minimum instance evidence requested from the operator is:

| Device or serial | Acquired date | Invoice/order reference | Warranty provider and end | Asset tag, if used | Planned retirement | Notes |
| --- | --- | --- | --- | --- | --- | --- |

## Verification

- each lifecycle record resolves to the intended Device Type or Module Type;
- no assigned type has duplicate Hardware Lifecycle records;
- every populated date has direct evidence and uses the correct date class;
- minimum availability and undated vintage/legacy status remain notices, not
  fabricated end dates;
- every contract assignment resolves to the exact Device and actual contract;
- serials and asset tags remain unique when non-empty;
- decommissioning Devices remain documented until disposal or archival is
  complete;
- every MCP write has a corresponding changelog entry under the batch change
  reference.

## References

- [NetBox Lifecycle plugin](https://github.com/DanSheps/netbox-lifecycle)
- [Raspberry Pi 5 product page](https://www.raspberrypi.com/products/raspberry-pi-5/)
- [Raspberry Pi longevity statement](https://www.raspberrypi.com/news/raspberry-pis-commitment-to-longevity-a-sustainable-advantage/)
- [Ubiquiti vintage and legacy products](https://help.ui.com/hc/en-us/articles/1500001268521-Ubiquiti-s-Vintage-and-Legacy-Products)
- [Ubiquiti security-update statement](https://dl.ui.com/compliance/Singapore_CLS.pdf)
