WITH NormalizedBOM AS
(
    SELECT

        /* Physical identifiers */

        bom.recid                      AS [BlueStar BOM RecId],
        bom.Id                         AS [BlueStar BOM Id],
        bom.bomlineid                  AS [BlueStar BOM Line Id],

        /* Matching fields */

        NULLIF(
            LTRIM(RTRIM(
                CAST(bom.bomid AS nvarchar(255))
            )),
            ''
        )                              AS [Parent Item Number],

        NULLIF(
            LTRIM(RTRIM(
                CAST(bom.itemid AS nvarchar(255))
            )),
            ''
        )                              AS [Child Item Number],

        NULLIF(
            LTRIM(RTRIM(
                CAST(bom.position AS nvarchar(100))
            )),
            ''
        )                              AS [Position],

        TRY_CAST(
            bom.bomqty AS decimal(38,12)
        )                              AS [Quantity],

        /* Audit */

        bom.createdby                  AS [Created By],
        bom.modifiedby                 AS [Modified By],

        bom.createdonpartition         AS [Upload Tracking DateTime],

        /* Refresh diagnostics */

        bom.SinkCreatedOn              AS [Sink Created On],
        bom.SinkModifiedOn             AS [Sink Modified On]

    FROM
        [lh_dataoperations_refinery].[__SCHEMA__].[bluestar_bom] bom

    WHERE
        bom.IsDelete IS NULL
),

CandidateCounts AS
(
    SELECT

        bom.*,

        COUNT(*) OVER
        (
            PARTITION BY
                bom.[Parent Item Number],
                bom.[Child Item Number],
                bom.[Position]
        ) AS [BOM Candidate Count],

        COUNT(*) OVER
        (
            PARTITION BY
                bom.[Parent Item Number],
                bom.[Child Item Number],
                bom.[Position],
                bom.[Quantity]
        ) AS [Candidate Count After Quantity]

    FROM NormalizedBOM bom
)

SELECT

    /* Business Key */

    [Parent Item Number],
    [Child Item Number],
    [Position],
    [Quantity],

    /* Physical identifiers */

    [BlueStar BOM RecId],
    [BlueStar BOM Id],
    [BlueStar BOM Line Id],

    /* Candidate diagnostics */

    [BOM Candidate Count],
    [Candidate Count After Quantity],

    /* Upload attribution */

    [Created By],
    [Modified By],
    [Upload Tracking DateTime],

    /* Refresh diagnostics */

    [Sink Created On],
    [Sink Modified On],

    SYSUTCDATETIME() AS [Snapshot Captured UTC]

FROM CandidateCounts;
