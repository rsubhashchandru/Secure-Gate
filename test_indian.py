"""Quick test: Indian Optimization Layer"""
from backend.phi_detector import get_phi_engine

print("Importing PHI engine...")
engine = get_phi_engine()
print("Engine initialized OK\n")

text = (
    "Patient Veerabhadra Rao S/O Subramaniam visited cardiology department "
    "at Apollo Hospital. Aadhaar: 1234 5678 9012. PAN: ABCDE1234F. "
    "Diagnosed with diabetes and hypertension. Prescribed metformin. "
    "Age 67 years old. Male. Phone: +919876543210."
)

results = engine.detect(text)
print(f"Total detections: {len(results)}\n")
print(f"{'Entity Type':<22} {'Text':<32} {'Score':>6}  {'Action':<16} {'Source'}")
print("-" * 100)
for d in results:
    t = d['text'][:30]
    print(f"{d['entity_type']:<22} {t:<32} {d['score']:>5.3f}  {d['action']:<16} {d['detected_by']}")

# Calculate mean confidence of MASKED entities
masked = [d for d in results if d['action'] == 'MASKED']
if masked:
    mean = sum(d['score'] for d in masked) / len(masked)
    print(f"\nMean MASKED confidence: {mean:.4f} ({mean*100:.2f}%)")
    print(f"Masked entities: {len(masked)}")
else:
    print("\nNo MASKED entities found.")

kept = [d for d in results if d['action'] in ('KEPT', 'AGE_AGGREGATED')]
print(f"Kept entities: {len(kept)}")
