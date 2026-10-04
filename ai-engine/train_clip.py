import json
import os
import torch
from pathlib import Path
from PIL import Image
from torch.utils.data import Dataset
from transformers import (
    CLIPProcessor,
    CLIPModel,
    Trainer,
    TrainingArguments,
    default_data_collator
)

class ILIDDataset(Dataset):
    """
    Dataset wrapper for the Industrial Language-Image Dataset (ILID)
    or any similarly formatted JSON-lines / JSON catalogue.
    """
    def __init__(self, data_dir: str, processor: CLIPProcessor, split="train"):
        self.data_dir = Path(data_dir)
        self.processor = processor
        self.samples = []

        metadata_files = self._find_metadata_files()
        if not metadata_files:
            print(f"Warning: no metadata file found under {self.data_dir}. Returning empty dataset.")
            return

        for metadata_file in metadata_files:
            self.samples.extend(self._load_metadata_file(metadata_file))

        self.samples = [sample for sample in self.samples if self._has_valid_image(sample)]

        if not self.samples:
            return

        # Basic split logic (80/20), while keeping at least one sample in each split when possible.
        if len(self.samples) == 1:
            split_samples = self.samples if split == "train" else []
        else:
            split_idx = max(1, int(len(self.samples) * 0.8))
            split_samples = self.samples[:split_idx] if split == "train" else self.samples[split_idx:]

        self.samples = split_samples

    @staticmethod
    def _flatten_attribute_values(value):
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (list, tuple)):
            flattened = []
            for item in value:
                if item is None:
                    continue
                flattened.append(str(item))
            return ", ".join(flattened)
        if isinstance(value, dict):
            parts = []
            for key, nested_value in value.items():
                nested_text = ILIDDataset._flatten_attribute_values(nested_value)
                if nested_text:
                    parts.append(f"{key}: {nested_text}")
            return "; ".join(parts)
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _first_non_empty(item, keys):
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if value not in (None, "", [], {}, ()):
                return ILIDDataset._flatten_attribute_values(value)
        return ""

    @staticmethod
    def _extract_text(item):
        candidates = [
            ILIDDataset._first_non_empty(item, ["label_short", "label", "category", "classification", "main_entity", "title", "name", "product_name"]),
            ILIDDataset._first_non_empty(item, ["description", "caption", "summary", "text", "details"]),
        ]

        cpv_results = item.get("cpv_results")
        if isinstance(cpv_results, dict):
            cpv_parts = []
            for property_name, values in cpv_results.items():
                flattened = ILIDDataset._flatten_attribute_values(values)
                if flattened:
                    cpv_parts.append(f"{property_name}: {flattened}")
            if cpv_parts:
                candidates.append("; ".join(cpv_parts))

        text = " | ".join(part for part in candidates if part)
        return text.strip() or "industrial product"

    def _find_metadata_files(self):
        candidates = [
            self.data_dir / "metadata.jsonl",
            self.data_dir / "metadata.json",
            self.data_dir / "items.jsonl",
            self.data_dir / "items.json",
        ]
        found = [path for path in candidates if path.exists()]
        if found:
            return found

        jsonl_files = sorted(self.data_dir.glob("*.jsonl"))
        if jsonl_files:
            return jsonl_files

        json_files = sorted(self.data_dir.glob("*.json"))
        return json_files

    def _load_metadata_file(self, metadata_file):
        rows = []
        if metadata_file.suffix.lower() == ".jsonl":
            with open(metadata_file, "r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict):
                        rows.append(item)
        else:
            with open(metadata_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)

            if isinstance(payload, dict):
                items = payload.get("data") or payload.get("items") or payload.get("records") or payload.get("rows")
                if isinstance(items, list):
                    rows.extend(item for item in items if isinstance(item, dict))
                else:
                    rows.append(payload)
            elif isinstance(payload, list):
                rows.extend(item for item in payload if isinstance(item, dict))

        return rows

    def _has_valid_image(self, item):
        image_path = self._resolve_image_path(item)
        return image_path is not None and image_path.exists()

    def _resolve_image_path(self, item):
        image_value = self._first_non_empty(item, ["image", "image_path", "path", "file_name", "filePath", "filename"])
        if not image_value:
            images = item.get("images")
            if isinstance(images, list) and images:
                first = images[0]
                if isinstance(first, str):
                    image_value = first
                elif isinstance(first, dict):
                    image_value = self._first_non_empty(first, ["image", "image_path", "path", "file_name", "filename"])

        if not image_value:
            return None

        candidate = Path(image_value)
        if candidate.is_absolute():
            return candidate

        for root in (self.data_dir, self.data_dir.parent, Path.cwd()):
            checked = root / candidate
            if checked.exists():
                return checked

        return self.data_dir / candidate

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        item = self.samples[idx]

        image_path = self._resolve_image_path(item)
        if image_path is None or not image_path.exists():
            image = Image.new("RGB", (224, 224), (255, 255, 255))
        else:
            try:
                image = Image.open(image_path).convert("RGB")
            except Exception:
                image = Image.new("RGB", (224, 224), (255, 255, 255))

        text = self._extract_text(item)

        inputs = self.processor(
            text=text,
            images=image,
            return_tensors="pt",
            padding="max_length",
            truncation=True,
            max_length=77,
        )

        normalized_inputs = {}
        for key, value in inputs.items():
            if hasattr(value, "squeeze"):
                normalized_inputs[key] = value.squeeze(0)
            elif isinstance(value, list):
                if value and isinstance(value[0], (list, tuple)):
                    normalized_inputs[key] = value[0]
                else:
                    normalized_inputs[key] = value
            else:
                normalized_inputs[key] = value

        return normalized_inputs


def train_model(data_dir: str, output_dir: str, model_name="openai/clip-vit-base-patch32", epochs=3):
    print(f"Loading processor and model from {model_name}...")
    processor = CLIPProcessor.from_pretrained(model_name)
    model = CLIPModel.from_pretrained(model_name)

    # Freeze vision encoder to save memory and only fine-tune the text/projection layers
    # (Optional, but highly recommended for limited hardware)
    for param in model.vision_model.parameters():
        param.requires_grad = False

    print("Preparing datasets...")
    train_dataset = ILIDDataset(data_dir, processor, split="train")
    eval_dataset = ILIDDataset(data_dir, processor, split="val")
    
    if len(train_dataset) == 0:
        print("No training data found. Please ensure the dataset is downloaded and formatted.")
        return

    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=8,
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_steps=10,
        learning_rate=5e-5,
        remove_unused_columns=False,
        push_to_hub=False,
        report_to="none",
        dataloader_num_workers=4
    )

    class CLIPTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            if "return_loss" in inputs:
                del inputs["return_loss"]
            outputs = model(**inputs, return_loss=True)
            loss = outputs.loss
            return (loss, outputs) if return_outputs else loss

    trainer = CLIPTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=default_data_collator,
    )

    print("Starting training...")
    trainer.train()
    
    print(f"Saving fine-tuned model to {output_dir}...")
    model.save_pretrained(output_dir)
    processor.save_pretrained(output_dir)
    print("Training complete!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fine-tune CLIP on Industrial Dataset")
    parser.add_argument("--data-dir", type=str, default="./data/ilid", help="Path to dataset directory")
    parser.add_argument("--output-dir", type=str, default="./models/industrial-clip-ft", help="Where to save the model")
    parser.add_argument("--epochs", type=int, default=3, help="Number of training epochs")
    
    args = parser.parse_args()
    
    # Ensure output dir exists
    os.makedirs(args.output_dir, exist_ok=True)
    
    train_model(args.data_dir, args.output_dir, epochs=args.epochs)
