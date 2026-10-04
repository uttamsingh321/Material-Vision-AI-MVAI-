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
        
        # Load the metadata (assuming ILID JSON structure or similar)
        # For this example, we expect a metadata.jsonl where each line is a dict:
        # {"image": "path/to/img.png", "label_short": "collet", "description": "..."}
        metadata_file = self.data_dir / "metadata.jsonl"
        if not metadata_file.exists():
            print(f"Warning: {metadata_file} not found. Returning empty dataset.")
            return
            
        with open(metadata_file, "r") as f:
            for line in f:
                if not line.strip(): continue
                item = json.loads(line)
                self.samples.append(item)
                
        # Basic split logic (80/20)
        split_idx = int(len(self.samples) * 0.8)
        if split == "train":
            self.samples = self.samples[:split_idx]
        else:
            self.samples = self.samples[split_idx:]

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        item = self.samples[idx]
        
        # Load image
        image_path = self.data_dir / item["image"]
        try:
            image = Image.open(image_path).convert("RGB")
        except Exception as e:
            # Fallback to a blank image if missing (or handle gracefully)
            image = Image.new("RGB", (224, 224), (255, 255, 255))
            
        # We can use label_long or description for the text
        text = f"{item.get('label_short', '')} - {item.get('description', '')}"
        
        # Process inputs
        inputs = self.processor(
            text=text,
            images=image,
            return_tensors="pt",
            padding="max_length",
            truncation=True,
            max_length=77
        )
        
        # Remove batch dimension added by processor
        inputs = {k: v.squeeze(0) for k, v in inputs.items()}
        return inputs


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
