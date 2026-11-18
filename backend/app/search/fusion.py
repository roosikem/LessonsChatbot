"""Merging keyword and vector rankings; shared by the memory store and the graph agent."""
import numpy as np


def rrf(*score_lists, k=60):
    """Reciprocal rank fusion, rescaled to 0..1. A document scoring 0 in a list gets nothing from that list,
    otherwise ties at 0 would be ranked by file order."""
    fused = np.zeros(len(score_lists[0]), dtype=np.float32)
    for scores in score_lists:
        ranks = np.argsort(-scores, kind="stable").argsort()
        fused += np.where(scores > 0, 1.0 / (k + ranks + 1), 0.0)
    return fused / fused.max() if fused.max() > 0 else fused


def fuse(vec_scores, kw_scores, settings):
    lists = []
    if settings.feature_vector_search or not settings.feature_keyword_search:
        lists.append(vec_scores)
    if settings.feature_keyword_search:
        lists.append(kw_scores)
    return rrf(*lists)
