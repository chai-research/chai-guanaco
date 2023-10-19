from abc import ABCMeta, abstractmethod
import copy

from transformers import AutoModelForSequenceClassification
from transformers import TrainingArguments, Trainer
import numpy as np

from chaiverse.dev import utils


class BaseRewardTrainer(metaclass=ABCMeta):
    _trainer_cls = Trainer
    _training_task = None

    def __init__(
            self,
            model_name,
            tokenize_loader,
            output_dir,
            num_labels=1,
            learning_rate=2e-5,
            num_train_epochs=1,
            optim='adamw_hf',
            bf16=False,
            logging_strategy='steps',
            logging_steps=50,
            eval_strategy='no',
            eval_steps=None,
            save_strategy='no',
            save_steps=None,
            per_device_batch_size=8,
            gradient_accumulation_steps=1,
            train_seed=1,
            device_map='auto',
    ):
        self.model_name = model_name
        self.tokenize_loader = tokenize_loader
        self.output_dir = output_dir
        self.num_labels = num_labels
        self.learning_rate = learning_rate
        self.num_train_epochs = num_train_epochs
        self.optim = optim
        self.bf16 = bf16
        self.logging_strategy = logging_strategy
        self.logging_steps = logging_steps
        self.eval_strategy = eval_strategy
        self.eval_steps = eval_steps
        self.save_strategy = save_strategy
        self.save_steps = save_steps
        self.per_device_batch_size = per_device_batch_size
        self.gradient_accumulation_steps = gradient_accumulation_steps
        self.train_seed = train_seed
        self.device_map = device_map

    def fit(self, data):
        self.tokenizer = self.tokenize_loader.load()
        data = self._format_data_by_training_task(data)
        self.instantiate_reward_model()
        self.instantiate_reward_trainer(data)
        self.trainer.train()

    def save(self, path=None):
        save_path = path or self.output_dir
        self.model.save_pretrained(save_path)

    def push_to_hub(self, hf_path, private=True):
        self.model.push_to_hub(hf_path, private=private)
        self.tokenizer.push_to_hub(hf_path, private=private)

    def instantiate_reward_model(self):
        self.model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
                num_labels=self.num_labels,
                problem_type=self._training_task,
                device_map=self.device_map,
                )

    def instantiate_reward_trainer(self, data):
        eval_dataset = data.get('validation', None)
        self.trainer = self._trainer_cls(
                model=self.model,
                args=self.training_config,
                tokenizer=self.tokenizer,
                train_dataset=data['train'],
                eval_dataset=eval_dataset,
                )

    @abstractmethod
    def _format_data_by_training_task(self, data):
        raise NotImplementedError

    @property
    def training_config(self):
        return TrainingArguments(
                output_dir=self.output_dir,
                learning_rate=self.learning_rate,
                num_train_epochs=self.num_train_epochs,
                logging_dir=f'{self.output_dir}/logs',
                logging_strategy=self.logging_strategy,
                logging_steps=self.logging_steps,
                evaluation_strategy=self.eval_strategy,
                eval_steps=self.eval_steps,
                save_strategy=self.save_strategy,
                save_steps=self.save_steps,
                bf16=self.bf16,
                optim=self.optim,
                logging_first_step=False,
                seed=self.train_seed,
                per_device_train_batch_size=self.per_device_batch_size,
                per_device_eval_batch_size=self.per_device_batch_size,
                gradient_accumulation_steps=self.gradient_accumulation_steps,
                )


class RewardRegressionTrainer(BaseRewardTrainer):
    _training_task = 'regression'

    def _format_data_by_training_task(self, data):
        data = utils.format_dataset_dtype(data, 'labels', 'float')
        return data


class RewardClassificationTrainer(BaseRewardTrainer):
    _training_task = 'single_label_classification'

    def _format_data_by_training_task(self, data):
        data = copy.copy(data)
        for fold, df in data.items():
            if np.array(df['labels']).ndim == 1:
                df = utils.format_dataset_dtype(df, 'labels', 'int64')
                data[fold] = self._format_one_hot_labels(df)
        return data

    def _format_one_hot_labels(self, df):
        labels = np.array(df['labels'])
        assert len(np.unique(labels)) <= self.num_labels
        one_hot_labels = np.eye(self.num_labels)[labels]
        one_hot_labels = one_hot_labels.astype(int).tolist()
        df = df.remove_columns('labels')
        df = df.add_column('labels', one_hot_labels)
        return df
