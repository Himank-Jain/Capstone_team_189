import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('Phase 3 MOCK_MODE fixtures', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv('VITE_MOCK_MODE', 'true');
  });

  it('serves both the high-confidence and UNKNOWN incident fixtures', async () => {
    const api = await import('./phase3Api');
    const highIncident = await api.getIncident('demo-high-confidence');
    const highExplanation = await api.getIncidentExplanation('demo-high-confidence');
    const highInvestigation = await api.getIncidentInvestigation('demo-high-confidence');
    const unknownIncident = await api.getIncident('demo-unknown');
    const unknownExplanation = await api.getIncidentExplanation('demo-unknown');
    const unknownInvestigation = await api.getIncidentInvestigation('demo-unknown');

    expect(highIncident.confidence).toBe('HIGH');
    expect(highExplanation.is_fallback).toBe(false);
    expect(highExplanation.sections.length).toBeGreaterThan(0);
    expect(highInvestigation.case.incident_id).toBe(highIncident.incident_id);
    expect(highInvestigation.explanation).toEqual(highExplanation);
    expect(highInvestigation.recommendations.length).toBeGreaterThan(0);
    expect(unknownIncident.candidate_causes[0]?.cause_category).toBe('UNKNOWN');
    expect(unknownExplanation.is_fallback).toBe(true);
    expect(unknownExplanation.sections.length).toBeGreaterThan(0);
    expect(unknownInvestigation.explanation.is_fallback).toBe(true);
    expect(unknownInvestigation.recommendations.length).toBeGreaterThan(0);
  });

  it('serves threat-specific, low-confidence generic, and UNKNOWN mitigation fixtures', async () => {
    const api = await import('./phase3Api');
    const high = await api.getIncidentMitigation('demo-high-confidence');
    const low = await api.getIncidentMitigation('demo-low-confidence');
    const unknown = await api.getIncidentMitigation('demo-unknown');
    const lowExplanation = await api.getIncidentExplanation('demo-low-confidence');

    expect(high.mitigation_mode).toBe('threat_specific');
    expect(high.threat?.match_confidence).toBe('HIGH');
    expect(high.mitigation.immediate[0]?.provider_specific).toBe(true);
    expect(lowExplanation.mitigation_mode).toBe('generic');
    expect(lowExplanation.matched_threats[0]?.match_confidence).toBe('LOW');
    expect(low.mitigation_mode).toBe('generic');
    expect(unknown.mitigation_mode).toBe('generic');
    expect(unknown.mitre_attack).toEqual([]);
  });
});
