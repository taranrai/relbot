import torch
import numpy as np 
from torch.utils.data import Dataset, DataLoader
from transformers import DistilBertTokenizerFast, DistilBertForSequenceClassification, Trainer, TrainingArguments
import pandas as pd
from sklearn.metrics import precision_recall_fscore_support
from torch.utils.data import Dataset


from transformers import DistilBertConfig
from transformers.models.distilbert.modeling_distilbert import DistilBertPreTrainedModel, DistilBertModel

from transformers import DefaultFlowCallback, ProgressCallback, PrinterCallback


class SocialMediaDataset(Dataset):
    def __init__(self, dataframe, tokenizer, max_length=8500, chunk_size=256, overlap=64):
        self.tokenizer = tokenizer
        self.data = dataframe
        self.max_length = max_length
        self.chunk_size = chunk_size
        self.overlap = overlap

    def __len__(self):
        return len(self.data)

    def _chunk_text(self, text):
        chunked_text = []
        for start in range(0, len(text), self.chunk_size - self.overlap):
            end = start + self.chunk_size
            chunked_text.append(text[start:end])
        return chunked_text

    def __getitem__(self, idx):
        text = self.data.loc[idx, 'text']
        label = self.data.loc[idx, 'label']
        
        # Chunk the text
        chunked_text = self._chunk_text(text)
        
        # Tokenize and embed each chunk
        embeddings = []
        for chunk in chunked_text:
            inputs = self.tokenizer(chunk, truncation=True, padding='max_length', max_length=self.max_length, return_tensors='pt')
            with torch.no_grad():
                outputs = model(**inputs)
                embeddings.append(outputs.last_hidden_state.mean(dim=1).squeeze().numpy())

        # Average embeddings
        avg_embedding = np.mean(embeddings, axis=0)

        inputs = {'input_embeddings': torch.tensor(avg_embedding, dtype=torch.float).unsqueeze(0)}
        inputs['labels'] = torch.tensor(label, dtype=torch.long)
        
        return inputs




class CustomDistilBertForSequenceClassification(DistilBertPreTrainedModel):
    def __init__(self, config):
        super().__init__(config)
        self.num_labels = config.num_labels

        self.distilbert = DistilBertModel(config)
        self.pre_classifier = torch.nn.Linear(config.dim, config.dim)
        self.classifier = torch.nn.Linear(config.dim, config.num_labels)
        self.dropout = torch.nn.Dropout(config.seq_classif_dropout)

        self.init_weights()

    def forward(self, input_embeddings, labels=None):
        distilbert_output = self.distilbert(inputs_embeds=input_embeddings)
        hidden_state = distilbert_output[0]  # (bs, seq_len, dim)
        pooled_output = hidden_state[:, 0]  # (bs, dim)
        pooled_output = self.pre_classifier(pooled_output)  # (bs, dim)
        pooled_output = torch.nn.ReLU()(pooled_output)  # (bs, dim)
        pooled_output = self.dropout(pooled_output)  # (bs, dim)
        logits = self.classifier(pooled_output)  # (bs, num_labels)

        if labels is not None:
            loss_fct = torch.nn.CrossEntropyLoss()
            loss = loss_fct(logits.view(-1, self.num_labels), labels.view(-1))
            return loss
        else:
            return logits



def compute_metrics(pred):
    labels = pred.label_ids
    preds = pred.predictions.argmax(-1)
    precision, recall, f1, _ = precision_recall_fscore_support(labels, preds, average='binary')
    return {'precision': precision, 'recall': recall, 'f1': f1}




tokenizer = DistilBertTokenizerFast.from_pretrained('distilbert-base-uncased')
config = DistilBertConfig.from_pretrained('distilbert-base-uncased', num_labels=2)
model = CustomDistilBertForSequenceClassification.from_pretrained('distilbert-base-uncased', config=config)


train_df = pd.read_csv('/vol/research/chiron/trans4/train_2.csv')
test_df = pd.read_csv('/vol/research/chiron/trans4/test.csv')



train_dataset = SocialMediaDataset(train_df, tokenizer)
test_dataset = SocialMediaDataset(test_df, tokenizer)

train_loader = DataLoader(train_dataset, batch_size=8, shuffle=True)
test_loader = DataLoader(test_dataset, batch_size=8)


# Create a list of callbacks without TensorBoardCallback
default_callbacks = [ProgressCallback, PrinterCallback]

training_args = TrainingArguments(
    output_dir='./results',
    num_train_epochs=3,
    per_device_train_batch_size=16,
    per_device_eval_batch_size=16,
    warmup_steps=500,
    weight_decay=0.01,
    logging_dir='./logs',
    logging_steps=10,
    evaluation_strategy='epoch',
    save_strategy='epoch',
    load_best_model_at_end=True,
    metric_for_best_model='recall',
    report_to=["wandb"],  # If you want to use other reporting tools like Weights & Biases, add them here
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=test_dataset,
    compute_metrics=compute_metrics,
    callbacks=default_callbacks  # Pass the updated list of callbacks to the Trainer
)

trainer.train()
trainer.evaluate()
