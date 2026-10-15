"""Teams 2026/27 on the v2 model

Folds the interim teams_* tables (pair choice released on the old system)
into v2: a Teams competition in season 2026/27 with 4 mini-tournament stages,
an entry per roster player, and mini-tournament 1's partner requests and pairs.
Stages gain the pair-choice deadline; pairs gain a creation time and one row
per player per stage. The teams_* tables are left in place (unused) until the
old-system cleanup.

Revision ID: c4f1a9e2b7d3
Revises: b7d2e4c1a9f0
Create Date: 2026-10-15
"""

from alembic import op

revision = "c4f1a9e2b7d3"
down_revision = "b7d2e4c1a9f0"
branch_labels = None
depends_on = None

SQL = r"""
ALTER TABLE stages ADD COLUMN pairing_deadline timestamp;
ALTER TABLE stages ADD COLUMN pairing_closed boolean NOT NULL DEFAULT false;
ALTER TABLE pairs ADD COLUMN created_at timestamp NOT NULL DEFAULT now();
ALTER TABLE pairs ADD CONSTRAINT pairs_entries_ordered CHECK (entry_a_id < entry_b_id);
ALTER TABLE pairs ADD CONSTRAINT pairs_stage_entry_a_key UNIQUE (stage_id, entry_a_id);
ALTER TABLE pairs ADD CONSTRAINT pairs_stage_entry_b_key UNIQUE (stage_id, entry_b_id);
ALTER TABLE partner_requests ADD CONSTRAINT partner_requests_not_self CHECK (from_entry_id <> to_entry_id);

DO $$
DECLARE
  comp_id bigint;
  stage1  integer;
BEGIN
  IF EXISTS (SELECT 1 FROM competitions WHERE format = 'teams') THEN
    RAISE EXCEPTION 'A Teams competition already exists';
  END IF;

  INSERT INTO competitions (season_id, event_slot_id, name, title, format, status, starts_on, ends_on, rules)
  VALUES (
    (SELECT id FROM seasons WHERE name = '2026/27'),
    (SELECT id FROM event_slots WHERE key = 'teams'),
    'PPL Teams 2026/27', 'PPL Teams', 'teams', 'planned', '2026-10-20', '2027-01-05',
    '{"mini_tournaments": 4, "rounds_per_mini_tournament": 3, "pairs_per_group": 4,
      "ratings": [500, 250, 125, 63, 31, 16], "set_points": {"win": 3, "draw": 1, "loss": 0},
      "sets_per_match": 3, "max_times_together": 3, "expulsion_max_rounds_played": 3}'::jsonb)
  RETURNING id INTO comp_id;

  INSERT INTO stages (competition_id, number, name, seeding_method, emits_award, status, pairing_deadline)
  SELECT comp_id, n, 'Mini-torneio ' || n, 'pairs_by_ranking_sum', true, 'planned',
         CASE WHEN n = 1 THEN (SELECT pairing_deadline FROM teams_mini_tournaments WHERE number = 1) END
  FROM generate_series(1, 4) n;
  SELECT id INTO stage1 FROM stages WHERE competition_id = comp_id AND number = 1;
  UPDATE stages SET pairing_closed = coalesce((SELECT pairing_closed FROM teams_mini_tournaments WHERE number = 1), false)
  WHERE id = stage1;

  INSERT INTO entries (competition_id, player_id, kind, status)
  SELECT comp_id, player_id, 'regular', 'active' FROM teams_players ORDER BY player_id;

  INSERT INTO partner_requests (stage_id, from_entry_id, to_entry_id, submitted_at)
  SELECT stage1, ef.id, et.id, r.created_at
  FROM teams_partner_requests r
  JOIN teams_mini_tournaments mt ON mt.id = r.mini_tournament_id AND mt.number = 1
  JOIN entries ef ON ef.competition_id = comp_id AND ef.player_id = r.player_id
  JOIN entries et ON et.competition_id = comp_id AND et.player_id = r.partner_id;

  INSERT INTO pairs (stage_id, entry_a_id, entry_b_id, formed_by, created_at)
  SELECT stage1, least(ea.id, eb.id), greatest(ea.id, eb.id),
         CASE p.source WHEN 'mutual' THEN 'mutual' WHEN 'auto' THEN 'ranking' ELSE 'manual' END,
         p.created_at
  FROM teams_pairs p
  JOIN teams_mini_tournaments mt ON mt.id = p.mini_tournament_id AND mt.number = 1
  JOIN entries ea ON ea.competition_id = comp_id AND ea.player_id = p.player_a_id
  JOIN entries eb ON eb.competition_id = comp_id AND eb.player_id = p.player_b_id;

  IF (SELECT count(*) FROM entries WHERE competition_id = comp_id) <> (SELECT count(*) FROM teams_players) THEN
    RAISE EXCEPTION 'Teams roster did not carry over';
  END IF;
  IF (SELECT count(*) FROM pairs WHERE stage_id = stage1) <> (SELECT count(*) FROM teams_pairs) THEN
    RAISE EXCEPTION 'Teams pairs did not carry over';
  END IF;
END $$;
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute(
        """
        DELETE FROM competitions WHERE format = 'teams';
        ALTER TABLE partner_requests DROP CONSTRAINT partner_requests_not_self;
        ALTER TABLE pairs DROP CONSTRAINT pairs_stage_entry_b_key;
        ALTER TABLE pairs DROP CONSTRAINT pairs_stage_entry_a_key;
        ALTER TABLE pairs DROP CONSTRAINT pairs_entries_ordered;
        ALTER TABLE pairs DROP COLUMN created_at;
        ALTER TABLE stages DROP COLUMN pairing_closed;
        ALTER TABLE stages DROP COLUMN pairing_deadline;
        """
    )
