-- ops.lineage: Upstream / downstream dependency graph
CREATE TABLE IF NOT EXISTS `ops.lineage` (
  downstream_table STRING NOT NULL,
  upstream_table STRING NOT NULL,
  dependency_type STRING NOT NULL -- 'DIRECT' | 'JOIN' | 'TRANSFORM'
);

