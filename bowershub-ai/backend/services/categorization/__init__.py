"""Finance categorization cascade (finance-categorization spec).

An ordered cascade of independently-testable tiers, each returning a uniform
`Decision`, behind one auditable write choke point. Tiers (fixed code order):

    tier 0  TransferDetector   (R6)
    tier 1  RuleEngine         (R2.1)
    tier 2  MerchantMemory     (R2.2/R3.2)
    tier 3  EmbeddingKNN       (R2.3)
    tier 4  LLMFallback        (R2.4)

The order is a correctness invariant (transfer-first / LLM-last, R6.4/R5.3);
only per-tier *enable* and *threshold* are DB config (finance.categorizer_config).
"""

from .base import Classifier, Decision, TxnContext

__all__ = ["Decision", "TxnContext", "Classifier"]
