"""Deterministic synthetic Analyst stub. No transport, secrets or provider selection."""
import json

from app.ai.analyst import AnalystInterpretation, AnalystProvenance, AnalystResponseV1
from app.ai.config import Protocol
from app.ai.contracts import (AnalysisResponse, Bias, Claim, EvidenceSufficiencyLabel, ProviderMetadata,
    TimeframeAnalysis, TradeStance, ValidationState)
from app.ai.evidence import EvidencePacket, QualityStatus


def mock_completion(prompt: str) -> str:
    value = json.loads(prompt)
    packet = EvidencePacket.model_validate(value['evidence_packet'])
    provenance = AnalystProvenance.model_validate(value['provenance'])
    ids = {tf:next(e.evidence_id for e in packet.evidence if e.timeframe == tf and e.quality == QualityStatus.VERIFIED)
           for tf in packet.requested_timeframes}
    claim = Claim(text='Synthetic fixture evidence is for offline validation only.', evidence_ids=tuple(ids.values()))
    analysis = AnalysisResponse(analysis_id=packet.analysis_id, bias=Bias.NEUTRAL, trade_stance=TradeStance.WAIT,
        rationale=(claim,), evidence_sufficiency=EvidenceSufficiencyLabel.SUFFICIENT,
        timeframes=tuple(TimeframeAnalysis(timeframe=tf,direction='NEUTRAL',supporting_evidence_ids=(ids[tf],))
                         for tf in packet.requested_timeframes), confidence_explanation=(claim,),
        provider_metadata=ProviderMetadata(provider_id=provenance.provider_id,model_id=provenance.model_id,
            protocol=Protocol.OPENAI_CHAT_COMPLETIONS, analysis_request_id=provenance.analysis_request_id,
            generated_at=provenance.created_at, validation_status=ValidationState.UNVERIFIED))
    scenario = AnalystInterpretation(text='Synthetic stub: wait for additional evidence.', market_evidence_ids=tuple(ids.values()))
    return AnalystResponseV1(analysis=analysis,bullish_scenario=scenario,bearish_scenario=scenario,
                            neutral_conditions=scenario).model_dump_json()
