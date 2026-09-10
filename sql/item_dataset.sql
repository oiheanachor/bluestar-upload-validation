/*
===============================================================================
BlueStar Item Validation Dataset
===============================================================================

Replace __SCHEMA__ at runtime:

    PROD  = pit_fo
    UAT1  = pit_uat1_fo
    UAT2  = pit_uat2_fo
    UAT3  = pit_uat3_fo
    SIT1  = pit_sit1_fo
    SIT2  = pit_sit2_fo
    SIT3  = pit_sit3_fo

Revision Match Key:

    New Item Number
    + New Variant Id
    + Revision
    + Minor Revision

Candidate resolution is performed later in Python:

    1. Status
    2. New Item Name
    3. AX Template
    4. ItemType
    5. Variant Type

Original Item Sheet extraction logic preserved:

    isnewest = 1
    OR isnewestapproved = 1

===============================================================================
*/

WITH FilteredBlueStarObject AS
(
    SELECT

        /* Physical BlueStar identifiers */

        bo.recid                         AS [BlueStar Object RecId],
        bo.Id                            AS [BlueStar Object Id],
        bo.uniquerev                     AS [BlueStar Unique Revision],

        /* Raw values retained for diagnostics */

        bo.objectid                      AS [Raw New Item Number],
        bo.variantid                     AS [Raw New Variant Id],
        bo.revisioncount                 AS [Raw Revision Count],

        /* Canonical matching values */

        NULLIF(
            LTRIM(RTRIM(CAST(bo.objectid AS nvarchar(255)))),
            ''
        )                                AS [New Item Number],

        COALESCE(
            NULLIF(
                LTRIM(RTRIM(CAST(bo.variantid AS nvarchar(255)))),
                ''
            ),
            ''
        )                                AS [New Variant Id],

        COALESCE(
            NULLIF(
                LTRIM(RTRIM(CAST(bo.revisioncount AS nvarchar(100)))),
                ''
            ),
            '0'
        )                                AS [Combined Revision],

        /* Item Sheet fields */

        bo.name                          AS [New Item Name],
        bo.classificationid              AS [Classification Id],

        bo.realcreateddate               AS [Created date],
        bo.realcreatedby                 AS [Created by],

        bo.changeddate                   AS [Changed date],
        bo.changedby                     AS [Changed by],

        bo.drawndate                     AS [Drawn date],
        bo.drawnby                       AS [Drawn by],

        bo.wfstage                       AS [Stage],
        bo.variantname                   AS [Variant Name],
        bo.revisiontype                  AS [Revision type],
        bo.objecttype                    AS [Object Type],
        bo.isbasevariant                 AS [Master Variant],
        bo.varianttype                   AS [Variant Type],
        bo.stampname                     AS [Stamp name],
        bo.status                        AS [Status],
        bo.ownerarea                     AS [Area],
        bo.baseclass                     AS [Classification],

        /* Diagnostics */

        bo.isnewest                      AS [Is Newest],
        bo.isnewestapproved              AS [Is Newest Approved],

        /* Audit */

        bo.createddatetime               AS [System Created DateTime],
        bo.createdby                     AS [System Created By],
        bo.createdtransactionid          AS [Created Transaction Id],

        bo.modifieddatetime              AS [System Modified DateTime],
        bo.modifiedby                    AS [System Modified By],
        bo.modifiedtransactionid         AS [Modified Transaction Id],

        /* Fabric refresh metadata */

        bo.SinkCreatedOn                 AS [Sink Created On],
        bo.SinkModifiedOn                AS [Sink Modified On]

    FROM
        [lh_dataoperations_refinery].[__SCHEMA__].[bluestar_object] bo

    WHERE
    (
        bo.isnewest = 1
        OR bo.isnewestapproved = 1
    )
    AND UPPER(LTRIM(RTRIM(bo.objecttype))) = 'ITEM'
),

ParsedRevision AS
(
    SELECT

        bo.*,

        CASE
            WHEN CHARINDEX('-', bo.[Combined Revision]) > 0
            THEN LEFT(
                bo.[Combined Revision],
                CHARINDEX('-', bo.[Combined Revision]) - 1
            )
            ELSE bo.[Combined Revision]
        END                              AS [Revision],

        CASE
            WHEN CHARINDEX('-', bo.[Combined Revision]) > 0
            THEN SUBSTRING(
                bo.[Combined Revision],
                CHARINDEX('-', bo.[Combined Revision]) + 1,
                LEN(bo.[Combined Revision])
            )
            ELSE '0'
        END                              AS [Minor Revision]

    FROM FilteredBlueStarObject bo
),

ObjectCandidates AS
(
    SELECT

        bo.*,

        COUNT(*) OVER
        (
            PARTITION BY
                bo.[New Item Number],
                bo.[New Variant Id],
                bo.[Revision],
                bo.[Minor Revision]
        )                                AS [Object Candidate Count]

    FROM ParsedRevision bo
)

SELECT

    /* Matching key */

    bo.[New Item Number],
    bo.[New Variant Id],
    bo.[Revision],
    bo.[Minor Revision],

    CONCAT(
        bo.[New Item Number],
        '|',
        bo.[New Variant Id],
        '|',
        bo.[Revision],
        '|',
        bo.[Minor Revision]
    )                                    AS [Revision Match Key],

    /* Raw values */

    bo.[Raw New Item Number],
    bo.[Raw New Variant Id],
    bo.[Raw Revision Count],
    bo.[Combined Revision],

    /* Physical BlueStar identifiers */

    bo.[BlueStar Object RecId],
    bo.[BlueStar Object Id],
    bo.[BlueStar Unique Revision],

    eo.recid                             AS [Engineering Object RecId],
    eo.Id                                AS [Engineering Object Id],

    /* Item Sheet columns */

    bo.[New Item Name],
    bo.[Classification Id],

    bo.[Created date],
    bo.[Created by],

    bo.[Changed date],
    bo.[Changed by],

    bo.[Drawn date],
    bo.[Drawn by],

    bo.[Stage],
    bo.[Variant Name],
    bo.[Revision type],
    bo.[Object Type],
    bo.[Master Variant],
    bo.[Variant Type],
    bo.[Stamp name],
    bo.[Status],
    bo.[Area],
    bo.[Classification],

    eo.axitemtemplate                    AS [AX Template],
    eo.itemunit                          AS [AX Unit],

    eo.itemgroup1                        AS [ItemGroup1-Product],
    eo.itemgroup2                        AS [ItemGroup2-Function],
    eo.itemgroup3                        AS [ItemGroup3-Discipline],

    eo.itemgroupid                       AS [Item Group],

    eo.itemtype                          AS [ItemType],
    eo.itemtypedetail                    AS [Item Type Detail],

    eo.axphantom                         AS [Phantom],
    eo.configurablemaster                AS [Master Configuration],
    eo.econmaster                        AS [eCon Master],

    eo.documenttype                      AS [Document Type],

    eo.primaryvendorid                   AS [Vendor],

    eo.externalitemid                    AS [External Item Number],
    eo.externalitemtxt                   AS [External Item Text],

    eo.bs_itemweight                     AS [Weight in kg],
    eo.bs_manueloverwrite                AS [Manual Weight],

    eo.stopexplosion                     AS [Stop Explosion],

    eo.significanttocertification        AS [Significant to Cert.],

    eo.bluestarrtk_designauthority       AS [Design Authority],
    eo.bluestarrtk_productline           AS [Product Line],
    eo.bluestarrtk_manufacturer          AS [Manufacturer],
    eo.bluestarrtk_customerassetcategory AS [Customer Asset Category],
    eo.bluestarrtk_econmodel             AS [ECON Model],
    eo.bluestarrtk_iamcapable            AS [iAM Capable],
    eo.bluestarrtk_createcustomerasset   AS [Create Customer Asset],

    /* Candidate diagnostics */

    bo.[Object Candidate Count],

    /* Selection diagnostics */

    bo.[Is Newest],
    bo.[Is Newest Approved],

    /* Audit */

    bo.[System Created DateTime],
    bo.[System Created By],
    bo.[Created Transaction Id],

    bo.[System Modified DateTime],
    bo.[System Modified By],
    bo.[Modified Transaction Id],

    /* Refresh metadata */

    bo.[Sink Created On],
    bo.[Sink Modified On],

    /* Snapshot metadata */

    SYSUTCDATETIME()                     AS [Snapshot Captured UTC]

FROM ObjectCandidates bo

LEFT JOIN
    [lh_dataoperations_refinery].[__SCHEMA__].[bluestar_engineeringobject] eo
        ON bo.[BlueStar Object RecId] = eo.bluestar_object;