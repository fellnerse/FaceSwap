import torch

from Configuration.config_general import MOST_RECENT_MODEL
from Utils.DataSplitter import DataSplitter
from Utils.Logging.LoggingUtils import Logger


class Trainer:
    def __init__(self, config):
        self.config = config
        if torch.cuda.device_count() > 1:
            self.config.batch_size *= torch.cuda.device_count()
        print('BatchSize:', self.config.batch_size)
        self.data_set = config.data_set()
        self.data_loader = DataSplitter(self.data_set, self.config.batch_size, validation_size=config.validation_size)
        self.model = config.model(**config.model_params, dataset=self.data_set,
                                  initial_batch_size=self.config.batch_size,
                                  data_loader=self.data_loader)

        self.logger = Logger(len(self.data_set), self.model, save_model_every_nth=self.config.save_model_every_nth,
                             shared_model_path=MOST_RECENT_MODEL)
        self.logger.log_config(config)

    def train(self):
        for current_epoch in range(self.config.max_epochs):
            self.model.set_train_mode(True)
            train_data_loader = self.data_loader.get_train_data_loader()
            info = self.model.train(train_data_loader, self.config.batch_size, current_epoch=current_epoch,
                                    validate=False, )

            # update frequency
            if current_epoch >= self.config.validation_periods[self.config.validate_index + 1]:
                self.config.validate_index += 1

            if current_epoch % self.config.validation_frequencies[self.config.validate_index] == 0:
                self.model.log(self.logger, current_epoch, *info, log_images=True)
                # do validation
                self.model.set_train_mode(False)
                val_data_loader = self.data_loader.get_validation_data_loader()
                info = self.model.train(val_data_loader, self.config.batch_size, current_epoch=current_epoch,
                                        validate=True)
                self.model.log_validation(self.logger, current_epoch, *info)
                self.model.set_train_mode(True)
            else:
                self.model.log(self.logger, current_epoch, *info)
