-- Businesses lookup table: maps long business_id to URL-friendly slug
CREATE TABLE IF NOT EXISTS businesses (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  business_id TEXT NOT NULL UNIQUE,
  slug TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  description TEXT DEFAULT '',
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_businesses_slug ON businesses(slug);
CREATE INDEX IF NOT EXISTS idx_businesses_business_id ON businesses(business_id);

-- RLS
ALTER TABLE businesses ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public can read active businesses"
  ON businesses FOR SELECT USING (is_active = true);

CREATE POLICY "Authenticated users can manage businesses"
  ON businesses FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');

-- updated_at trigger
CREATE TRIGGER update_businesses_updated_at
  BEFORE UPDATE ON businesses
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Seed: existing business case
INSERT INTO businesses (business_id, slug, display_name, description) VALUES
('住宅塗装リフォーム向け顧客要望反映型自動見積積算SaaS', 'tosou-mitsumori', '塗装見積もり自動化', '住宅塗装リフォーム向けAI見積もり自動化SaaS')
ON CONFLICT (business_id) DO NOTHING;
