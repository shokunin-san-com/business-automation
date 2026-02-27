-- Row Level Security policies

-- Enable RLS on all tables
ALTER TABLE posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE authors ENABLE ROW LEVEL SECURITY;
ALTER TABLE staff ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE article_ideas ENABLE ROW LEVEL SECURITY;
ALTER TABLE article_generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE site_settings ENABLE ROW LEVEL SECURITY;

-- Posts: public can read published, authenticated can CRUD
CREATE POLICY "Public can read published posts"
  ON posts FOR SELECT
  USING (status = 'published' AND published_at <= now());

CREATE POLICY "Authenticated users can manage posts"
  ON posts FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');

-- Authors: public read, authenticated manage
CREATE POLICY "Public can read authors"
  ON authors FOR SELECT
  USING (true);

CREATE POLICY "Authenticated users can manage authors"
  ON authors FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');

-- Staff: authenticated only
CREATE POLICY "Authenticated users can read staff"
  ON staff FOR SELECT
  USING (auth.role() = 'authenticated');

CREATE POLICY "Authenticated users can manage staff"
  ON staff FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');

-- Contacts: anyone can insert, authenticated can read
CREATE POLICY "Anyone can submit contact"
  ON contacts FOR INSERT
  WITH CHECK (true);

CREATE POLICY "Authenticated users can read contacts"
  ON contacts FOR SELECT
  USING (auth.role() = 'authenticated');

-- Article ideas: authenticated only
CREATE POLICY "Authenticated users can manage ideas"
  ON article_ideas FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');

-- Article generations: authenticated only
CREATE POLICY "Authenticated users can manage generations"
  ON article_generations FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');

-- Site settings: authenticated only
CREATE POLICY "Authenticated users can manage settings"
  ON site_settings FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');
