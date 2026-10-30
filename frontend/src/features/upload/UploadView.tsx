import React, { useEffect, useState } from 'react';
import {
  Upload,
  FileArchive,
  FileSpreadsheet,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Download,
  HelpCircle,
  Play,
  ArrowRight,
  ShieldAlert,
} from 'lucide-react';
import { api } from '../../api/client';
import { CaseRole, UploadTemplateResponse, ValidationReport } from '../../api/types';
import { GlassBadge, GlassButton, GlassCard, GlassInput, GlassSelect } from '../../components/glass';

interface UploadViewProps {
  canUpload: boolean;
  onCaseCreated: (newCaseId: string) => void;
  onToast: (msg: string, tone?: 'cyan' | 'emerald' | 'crimson' | 'amber') => void;
}

export const UploadView: React.FC<UploadViewProps> = ({
  canUpload,
  onCaseCreated,
  onToast,
}) => {
  const [template, setTemplate] = useState<UploadTemplateResponse | null>(null);
  const [showHelp, setShowHelp] = useState(true);
  const [uploadMode, setUploadMode] = useState<'zip' | 'csv'>('csv');

  const [zipFile, setZipFile] = useState<File | null>(null);
  const [personsFile, setPersonsFile] = useState<File | null>(null);
  const [relationshipsFile, setRelationshipsFile] = useState<File | null>(null);
  const [communicationsFile, setCommunicationsFile] = useState<File | null>(null);

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [validating, setValidating] = useState(false);
  const [report, setReport] = useState<ValidationReport | null>(null);

  const [caseName, setCaseName] = useState('Operation Coastal Corridor');
  const [caseDesc, setCaseDesc] = useState('Port logistics & financial audit network uploaded for link analysis');
  const [caseRole, setCaseRole] = useState<CaseRole>('investigation');
  const [isSynthetic, setIsSynthetic] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createdCaseId, setCreatedCaseId] = useState<string | null>(null);
  const [runningAnalysis, setRunningAnalysis] = useState(false);

  useEffect(() => {
    api.getUploadTemplate().then(setTemplate).catch(() => null);
  }, []);

  if (!canUpload) {
    return (
      <GlassCard className="p-10 text-center space-y-3" variant="crimson">
        <ShieldAlert className="w-10 h-10 text-[#ff3b5c] mx-auto" />
        <h2 className="text-lg font-bold text-white">Investigator or Administrator Role Required</h2>
        <p className="text-xs text-slate-300 max-w-md mx-auto">
          Viewer accounts have read-only access and cannot upload new cases. Use the Demo User Switcher in the top-right bar to switch to an Investigator or Admin role.
        </p>
      </GlassCard>
    );
  }

  const handleDownloadExamples = () => {
    if (!template?.example) return;
    Object.entries(template.example).forEach(([filename, content]) => {
      const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    });
    onToast('Downloaded example CSV templates', 'cyan');
  };

  const handleLoadSampleFiles = () => {
    if (!template?.example) return;
    const pBlob = new Blob([template.example['persons.csv'] || ''], { type: 'text/csv' });
    const rBlob = new Blob([template.example['relationships.csv'] || ''], { type: 'text/csv' });
    const cBlob = new Blob([template.example['communications.csv'] || ''], { type: 'text/csv' });
    setUploadMode('csv');
    setPersonsFile(new File([pBlob], 'persons.csv', { type: 'text/csv' }));
    setRelationshipsFile(new File([rBlob], 'relationships.csv', { type: 'text/csv' }));
    setCommunicationsFile(new File([cBlob], 'communications.csv', { type: 'text/csv' }));
    onToast('Loaded example persons.csv, relationships.csv & communications.csv', 'emerald');
  };

  const buildFormData = () => {
    const fd = new FormData();
    if (uploadMode === 'zip' && zipFile) {
      fd.append('file', zipFile);
    } else {
      if (personsFile) fd.append('persons', personsFile);
      if (relationshipsFile) fd.append('relationships', relationshipsFile);
      if (communicationsFile) fd.append('communications', communicationsFile);
    }
    return fd;
  };

  const handleValidate = async () => {
    setValidating(true);
    try {
      const fd = buildFormData();
      const res = await api.validateCaseUpload(fd);
      setReport(res);
      setStep(2);
      onToast(res.valid ? 'Validation passed with 0 errors' : 'Validation found errors', res.valid ? 'emerald' : 'crimson');
    } catch (err: any) {
      onToast(err?.message || 'Validation failed', 'crimson');
    } finally {
      setValidating(false);
    }
  };

  const handleCreateCase = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!report?.valid) return;
    setCreating(true);
    try {
      const fd = buildFormData();
      fd.append('name', caseName);
      fd.append('description', caseDesc);
      fd.append('role', caseRole);
      fd.append('is_synthetic', String(isSynthetic));
      const res = await api.createCaseUpload(fd, {
        name: caseName,
        description: caseDesc,
        role: caseRole,
        is_synthetic: isSynthetic,
        report,
      });
      if (res.case_id) {
        setCreatedCaseId(res.case_id);
        setStep(3);
        onToast(`Created isolated case ${res.case_id}`, 'emerald');
      }
    } catch (err: any) {
      if (err?.detail?.report) {
        setReport(err.detail.report);
      }
      onToast(err?.message || 'Case creation failed', 'crimson');
    } finally {
      setCreating(false);
    }
  };

  const handleRunAndOpen = async () => {
    if (!createdCaseId) return;
    setRunningAnalysis(true);
    try {
      // Run both modes so the case is ready whichever view the investigator picks.
      const runs = [await api.runAnalysis(createdCaseId, 'observed_only'), await api.runAnalysis(createdCaseId, 'observed_plus_inferred')];
      const bad = runs.find((r) => r.run.status !== 'completed');
      if (bad) onToast(`Analysis ${bad.run.status}: ${bad.run.error || 'see run details'}`, bad.run.status === 'partial' ? 'amber' : 'crimson');
      else onToast(`Analysis completed for ${createdCaseId}`, 'emerald');
      onCaseCreated(createdCaseId);
    } catch (err: any) {
      onToast(err?.message || 'Analysis failed', 'crimson');
    } finally {
      setRunningAnalysis(false);
    }
  };

  const canValidate =
    (uploadMode === 'zip' && Boolean(zipFile)) ||
    (uploadMode === 'csv' && Boolean(personsFile && relationshipsFile));

  return (
    <div className="space-y-5">
      {/* Header & Mandatory Rule */}
      <GlassCard className="p-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <GlassBadge tone="cyan">3-Step Validated Ingestion</GlassBadge>
            <span className="text-xs font-semibold text-amber-300">
              Each upload creates a new case. People are never merged automatically.
            </span>
          </div>
          <h1 className="text-lg font-bold text-white flex items-center gap-2">
            <Upload className="w-5 h-5 text-[#22d3ee]" />
            Upload New Investigation Case
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <GlassButton size="sm" variant="secondary" onClick={handleLoadSampleFiles}>
            Load Sample Case Files
          </GlassButton>
          <GlassButton size="sm" variant="primary" onClick={handleDownloadExamples}>
            <Download className="w-3.5 h-3.5" />
            Download Example CSVs
          </GlassButton>
          <GlassButton size="sm" variant="ghost" onClick={() => setShowHelp((v) => !v)}>
            <HelpCircle className="w-4 h-4" />
            {showHelp ? 'Hide Template Rules' : 'Show Template Rules'}
          </GlassButton>
        </div>
      </GlassCard>

      {/* Expandable Template Help Card */}
      {showHelp && template && (
        <GlassCard className="p-5 space-y-4 border-cyan-500/30">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-cyan-200">Required CSV Schema & Safety Rules</h2>
            <span className="text-xs text-slate-400">{template.how}</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
            {Object.entries(template.files).map(([name, spec]) => (
              <div key={name} className="p-3 rounded-[14px] bg-white/[0.04] border border-white/[0.08] space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-white">{name}.csv</span>
                  <GlassBadge tone={spec.required_file ? 'crimson' : 'slate'}>
                    {spec.required_file ? 'Required' : 'Optional'}
                  </GlassBadge>
                </div>
                <div className="text-slate-300">
                  <span className="text-slate-400">Required columns: </span>
                  <span className="font-mono text-cyan-300">{spec.required_columns.join(', ')}</span>
                </div>
                <div className="text-slate-400">
                  <span>Optional: </span>
                  <span className="font-mono text-slate-300">{spec.optional_columns.join(', ')}</span>
                </div>
              </div>
            ))}
          </div>
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs text-slate-300">
            {template.rules.map((r, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[#22d3ee] mt-1.5 shrink-0" />
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </GlassCard>
      )}

      {/* 3-Step Progress Bar */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { n: 1, title: 'Step 1: Select ZIP or CSVs' },
          { n: 2, title: 'Step 2: Dry-Run Validation Report' },
          { n: 3, title: 'Step 3: Create Isolated Case & Run Analysis' },
        ].map((s) => (
          <div
            key={s.n}
            className={`p-3 rounded-[14px] border text-xs font-semibold flex items-center gap-2.5 ${
              step === s.n
                ? 'bg-[#22d3ee]/15 border-[#22d3ee]/50 text-cyan-200'
                : step > s.n
                ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300'
                : 'bg-white/[0.03] border-white/[0.08] text-slate-400'
            }`}
          >
            <span className="w-6 h-6 rounded-full bg-white/10 flex items-center justify-center font-mono">
              {s.n}
            </span>
            <span>{s.title}</span>
          </div>
        ))}
      </div>

      {/* Step 1: Dropzones */}
      <GlassCard className="p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-white">Step 1 — Select Source Files</h2>
          <div className="flex items-center gap-1 p-1 rounded-[12px] bg-white/[0.05] border border-white/[0.1]">
            <button
              type="button"
              onClick={() => setUploadMode('csv')}
              className={`px-3 py-1 rounded-[9px] text-xs font-medium ${
                uploadMode === 'csv' ? 'bg-[#22d3ee]/20 text-cyan-200' : 'text-slate-400'
              }`}
            >
              Separate CSV Files
            </button>
            <button
              type="button"
              onClick={() => setUploadMode('zip')}
              className={`px-3 py-1 rounded-[9px] text-xs font-medium ${
                uploadMode === 'zip' ? 'bg-[#22d3ee]/20 text-cyan-200' : 'text-slate-400'
              }`}
            >
              Single ZIP Archive
            </button>
          </div>
        </div>

        {uploadMode === 'zip' ? (
          <label
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const f = e.dataTransfer.files?.[0];
              if (f && f.name.toLowerCase().endsWith('.zip')) setZipFile(f);
              else onToast('Drop a .zip file here, or switch to Separate CSV Files.', 'amber');
            }}
            className="block p-8 rounded-[18px] border-2 border-dashed border-white/[0.18] hover:border-[#22d3ee] bg-white/[0.03] text-center cursor-pointer transition"
          >
            <FileArchive className="w-8 h-8 text-[#22d3ee] mx-auto mb-2" />
            <div className="text-sm font-semibold text-white">
              {zipFile ? zipFile.name : 'Click or drop a .zip archive containing persons.csv & relationships.csv'}
            </div>
            <div className="text-xs text-slate-400 mt-1">Max 25 MB compressed / 150 MB uncompressed</div>
            <input
              type="file"
              accept=".zip"
              className="hidden"
              onChange={(e) => setZipFile(e.target.files?.[0] || null)}
            />
          </label>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[
              { label: 'persons.csv (Required)', file: personsFile, setter: setPersonsFile },
              { label: 'relationships.csv (Required)', file: relationshipsFile, setter: setRelationshipsFile },
              { label: 'communications.csv (Optional)', file: communicationsFile, setter: setCommunicationsFile },
            ].map((slot) => (
              <label
                key={slot.label}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  const f = e.dataTransfer.files?.[0];
                  if (f && f.name.toLowerCase().endsWith('.csv')) slot.setter(f);
                  else onToast('Drop a .csv file on this slot.', 'amber');
                }}
                className={`p-5 rounded-[16px] border-2 border-dashed text-center cursor-pointer transition ${
                  slot.file
                    ? 'border-emerald-400/50 bg-emerald-500/[0.06]'
                    : 'border-white/[0.16] hover:border-[#22d3ee] bg-white/[0.03]'
                }`}
              >
                <FileSpreadsheet className="w-6 h-6 text-[#22d3ee] mx-auto mb-2" />
                <div className="text-xs font-semibold text-white">{slot.label}</div>
                <div className="font-mono text-[11px] text-emerald-300 mt-1 truncate">
                  {slot.file ? `${slot.file.name} (${slot.file.size} B)` : 'Click to select CSV'}
                </div>
                <input
                  type="file"
                  accept=".csv"
                  className="hidden"
                  onChange={(e) => slot.setter(e.target.files?.[0] || null)}
                />
              </label>
            ))}
          </div>
        )}

        <div className="flex justify-end">
          <GlassButton
            variant="primary"
            disabled={!canValidate || validating}
            onClick={handleValidate}
          >
            {validating ? 'Validating Schema & Referential Integrity...' : 'Step 2: Validate Files (Dry Run)'}
            <ArrowRight className="w-4 h-4" />
          </GlassButton>
        </div>
      </GlassCard>

      {/* Step 2: Validation Report */}
      {report && (
        <GlassCard className="p-5 space-y-4" variant={report.valid ? 'emerald' : 'crimson'}>
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-white flex items-center gap-2">
              {report.valid ? (
                <>
                  <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                  Step 2 — Validation Passed (Ready to Create Isolated Case)
                </>
              ) : (
                <>
                  <XCircle className="w-5 h-5 text-rose-400" />
                  Step 2 — Validation Rejected (Fix Errors Below)
                </>
              )}
            </h2>
            {report.sha256 && (
              <span className="font-mono text-[11px] text-slate-400">SHA-256: {report.sha256.slice(0, 16)}...</span>
            )}
          </div>

          {report.counts && (
            <div className="grid grid-cols-3 gap-3 text-xs">
              <div className="p-3 rounded-[12px] bg-white/[0.04] border border-white/[0.08]">
                <span className="text-slate-400 block">{report.valid ? 'Validated' : 'Rows read'} persons</span>
                <span className="font-mono text-lg font-bold text-white">{report.counts.persons}</span>
              </div>
              <div className="p-3 rounded-[12px] bg-white/[0.04] border border-white/[0.08]">
                <span className="text-slate-400 block">{report.valid ? 'Validated' : 'Rows read'} relationships</span>
                <span className="font-mono text-lg font-bold text-white">{report.counts.relationships}</span>
              </div>
              <div className="p-3 rounded-[12px] bg-white/[0.04] border border-white/[0.08]">
                <span className="text-slate-400 block">{report.valid ? 'Validated' : 'Rows read'} communications</span>
                <span className="font-mono text-lg font-bold text-white">{report.counts.communications}</span>
              </div>
            </div>
          )}

          {report.relationship_types && report.relationship_types.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="text-slate-400">Detected Relationship Types:</span>
              {report.relationship_types.map((rt) => (
                <GlassBadge key={rt} tone="cyan">
                  {rt}
                </GlassBadge>
              ))}
            </div>
          )}

          {report.errors.length > 0 && (
            <div className="p-3.5 rounded-[14px] bg-rose-500/15 border border-rose-500/40 space-y-1 text-xs text-rose-200">
              <div className="font-bold">Errors ({report.errors.length}):</div>
              <ul className="list-disc list-inside space-y-1 font-mono">
                {report.errors.map((e, idx) => (
                  <li key={idx}>{e}</li>
                ))}
              </ul>
            </div>
          )}

          {report.warnings.length > 0 && (
            <div className="p-3.5 rounded-[14px] bg-amber-500/12 border border-amber-500/35 space-y-1 text-xs text-amber-200">
              <div className="font-bold flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5" /> Warnings ({report.warnings.length}):
              </div>
              <ul className="list-disc list-inside space-y-1">
                {report.warnings.map((w, idx) => (
                  <li key={idx}>{w}</li>
                ))}
              </ul>
            </div>
          )}
        </GlassCard>
      )}

      {/* Step 3: Case Metadata & Creation */}
      {report?.valid && (
        <GlassCard className="p-5 space-y-4">
          <h2 className="text-sm font-bold text-white">Step 3 — Case Metadata & Execution</h2>
          {!createdCaseId ? (
            <form onSubmit={handleCreateCase} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Case Name *</label>
                  <GlassInput
                    required
                    minLength={3}
                    value={caseName}
                    onChange={(e) => setCaseName(e.target.value)}
                    placeholder="e.g. Operation Coastal Corridor"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Case Role</label>
                  <GlassSelect
                    value={caseRole}
                    onChange={(e) => setCaseRole(e.target.value as CaseRole)}
                    className="w-full"
                  >
                    <option value="investigation">investigation (Live / Operational Case)</option>
                    <option value="benchmark">benchmark (Link-Recovery Evaluation)</option>
                    <option value="centrality_example">centrality_example (Structural Reference)</option>
                  </GlassSelect>
                </div>
              </div>
              <div>
                <label className="block text-xs text-slate-300 mb-1">Case Description</label>
                <GlassInput
                  value={caseDesc}
                  onChange={(e) => setCaseDesc(e.target.value)}
                  placeholder="Brief scope and provenance notes..."
                />
              </div>
              <div className="flex items-center justify-between pt-2">
                <label className="inline-flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={isSynthetic}
                    onChange={(e) => setIsSynthetic(e.target.checked)}
                    className="rounded border-white/20 bg-white/10 text-[#22d3ee]"
                  />
                  Mark dataset as synthetic / training scenario
                </label>
                <GlassButton type="submit" variant="emerald" size="lg" disabled={creating}>
                  {creating ? 'Creating Isolated Case...' : 'Create Isolated Case'}
                </GlassButton>
              </div>
            </form>
          ) : (
            <div className="p-5 rounded-[16px] bg-emerald-500/10 border border-emerald-500/35 flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="text-xs text-emerald-300 font-semibold uppercase tracking-wider">
                  New Case Created Successfully
                </div>
                <div className="font-mono text-lg font-bold text-white mt-0.5">{createdCaseId}</div>
                <div className="text-xs text-slate-300 mt-1">
                  All records have been isolated under {createdCaseId}. Run the analysis pipeline to compute centrality and link rankings.
                </div>
              </div>
              <GlassButton
                variant="primary"
                size="lg"
                disabled={runningAnalysis}
                onClick={handleRunAndOpen}
              >
                <Play className="w-4 h-4" />
                {runningAnalysis ? 'Running Analysis...' : 'Run Analysis & Open Network Graph'}
              </GlassButton>
            </div>
          )}
        </GlassCard>
      )}
    </div>
  );
};
