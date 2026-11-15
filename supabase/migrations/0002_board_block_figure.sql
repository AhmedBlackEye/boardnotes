-- Q-4: diagram blocks carry a figure (redrawn chart / Mermaid, or the board crop). Shape: contracts DiagramFigure.
alter table board_blocks add column if not exists figure jsonb;
